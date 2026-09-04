from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from asset_provenance_toolkit.png_backend import UnreadablePngError, embed_png, extract_png, strip_png
from asset_provenance_toolkit.schema import Provenance


def test_extract_returns_none_when_nothing_embedded(sample_png: Path):
    assert extract_png(sample_png) is None


def test_embed_then_extract_roundtrips(sample_png: Path):
    provenance = Provenance(capability="mock-generate", provider="mock", params={"prompt": "a cat"})
    embed_png(sample_png, provenance)
    restored = extract_png(sample_png)
    assert restored == provenance


def test_embed_is_lossless_for_pixel_data(sample_png: Path):
    with Image.open(sample_png) as before:
        before_pixels = list(before.convert("RGB").getdata())

    embed_png(sample_png, Provenance(capability="c", provider="p", params={}))

    with Image.open(sample_png) as after:
        after_pixels = list(after.convert("RGB").getdata())
    assert before_pixels == after_pixels


def test_embed_preserves_other_existing_text_chunks(sample_png: Path):
    # Simulate another tool having already written its own metadata chunk.
    with Image.open(sample_png) as img:
        img.load()
        info = PngImagePlugin.PngInfo()
        info.add_text("some-other-tool", "unrelated metadata")
        pixel_img = img.copy()
    pixel_img.save(sample_png, pnginfo=info)

    embed_png(sample_png, Provenance(capability="c", provider="p", params={}))

    with Image.open(sample_png) as img:
        img.load()
        assert img.text.get("some-other-tool") == "unrelated metadata"
    assert extract_png(sample_png) is not None


def test_re_embed_replaces_stale_provenance_not_duplicates_it(sample_png: Path):
    embed_png(sample_png, Provenance(capability="first", provider="p", params={}))
    embed_png(sample_png, Provenance(capability="second", provider="p", params={}))
    restored = extract_png(sample_png)
    assert restored.capability == "second"


def test_strip_removes_provenance_and_reports_true(sample_png: Path):
    embed_png(sample_png, Provenance(capability="c", provider="p", params={}))
    removed = strip_png(sample_png)
    assert removed is True
    assert extract_png(sample_png) is None


def test_strip_on_file_with_no_provenance_is_a_noop_reporting_false(sample_png: Path):
    removed = strip_png(sample_png)
    assert removed is False


def test_embed_on_unreadable_file_raises_unreadable_png_error(tmp_path: Path):
    fake_png = tmp_path / "not-really.png"
    fake_png.write_bytes(b"definitely not PNG data")
    with pytest.raises(UnreadablePngError, match="not a readable PNG"):
        embed_png(fake_png, Provenance(capability="c", provider="p", params={}))


def test_write_phase_failure_is_not_mislabeled_as_unreadable_png(sample_png: Path, monkeypatch):
    # A permission-denied/disk-full failure happens at save() time, on a
    # perfectly valid, fully-readable PNG - it must propagate as its own
    # exception type, not get caught and reported as "not a readable PNG",
    # which would send a user down the wrong troubleshooting path entirely.
    import os

    def failing_replace(src, dst, *args, **kwargs):
        raise PermissionError("permission denied (simulated)")

    # The backend writes a sibling temp file and renames it into place; the
    # rename is where a permissions failure on the target directory lands.
    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(PermissionError):
        embed_png(sample_png, Provenance(capability="c", provider="p", params={}))


def test_large_payload_is_written_as_compressed_ztxt_and_still_roundtrips(sample_png: Path):
    import zlib

    provenance = Provenance(
        capability="c", provider="p", params={"prompt": "x" * 5000}
    )
    embed_png(sample_png, provenance)

    with Image.open(sample_png) as img:
        img.load()
        # Pillow exposes zTXt content through the same `.text` dict as tEXt
        # (transparently decompressed), so round-tripping is unaffected...
        assert extract_png(sample_png) == provenance
        # ...but the chunk on disk is verifiably compressed: find the raw
        # zTXt chunk and confirm its payload zlib-decompresses to our JSON.
        with open(sample_png, "rb") as fh:
            raw = fh.read()
    chunk_start = raw.index(b"zTXt")
    length = int.from_bytes(raw[chunk_start - 4 : chunk_start], "big")
    chunk_data = raw[chunk_start + 4 : chunk_start + 4 + length]
    keyword, _null, compression_method, compressed = chunk_data.split(b"\x00", 1)[0], None, None, None
    assert keyword == b"ai-provenance"
    # After the keyword's null terminator comes a 1-byte compression method,
    # then the zlib-compressed text.
    rest = chunk_data[len(keyword) + 1 :]
    compressed_text = rest[1:]
    assert zlib.decompress(compressed_text).decode("latin-1") == provenance.to_json()


def test_small_payload_is_not_compressed(sample_png: Path):
    embed_png(sample_png, Provenance(capability="c", provider="p", params={}))
    with open(sample_png, "rb") as fh:
        raw = fh.read()
    assert b"zTXt" not in raw
    assert b"tEXt" in raw


def test_strip_preserves_other_text_chunks(sample_png: Path):
    with Image.open(sample_png) as img:
        img.load()
        info = PngImagePlugin.PngInfo()
        info.add_text("some-other-tool", "keep me")
        pixel_img = img.copy()
    pixel_img.save(sample_png, pnginfo=info)
    embed_png(sample_png, Provenance(capability="c", provider="p", params={}))

    strip_png(sample_png)

    with Image.open(sample_png) as img:
        img.load()
        assert img.text.get("some-other-tool") == "keep me"


def test_embed_leaves_every_other_chunk_byte_for_byte(sample_png: Path):
    """Not merely 'same pixels': the original encoder's IDAT bytes survive, so
    a checksum of the pixel stream taken before embedding still matches."""
    import struct

    def chunks(raw: bytes):
        out, off = [], 8
        while off < len(raw):
            (length,) = struct.unpack(">I", raw[off : off + 4])
            ctype = raw[off + 4 : off + 8]
            out.append((ctype, raw[off + 8 : off + 8 + length]))
            off += 12 + length
        return out

    before = chunks(sample_png.read_bytes())
    embed_png(sample_png, Provenance(capability="c", provider="p", params={}))
    after = chunks(sample_png.read_bytes())
    assert [c for c in after if c[0] != b"tEXt"] == before
    assert [c[0] for c in after].index(b"tEXt") == len(after) - 2  # right before IEND


def test_a_truncated_png_is_unreadable_not_a_crash(sample_png: Path):
    raw = sample_png.read_bytes()
    sample_png.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(UnreadablePngError, match="not a readable PNG"):
        extract_png(sample_png)


def test_a_corrupt_provenance_chunk_crc_is_refused(sample_png: Path):
    embed_png(sample_png, Provenance(capability="c", provider="p", params={}))
    raw = bytearray(sample_png.read_bytes())
    i = raw.index(b"tEXt")
    raw[i + 8] ^= 0xFF  # flip a byte of the keyword; the stored CRC no longer matches
    sample_png.write_bytes(bytes(raw))
    with pytest.raises(UnreadablePngError, match="bad CRC"):
        extract_png(sample_png)


def test_non_latin1_provenance_written_by_another_tool_is_read_from_itxt(sample_png: Path):
    """Pillow writes iTXt for text it cannot encode as latin-1; a reader that
    only understood tEXt would silently return None for such files."""
    provenance = Provenance(capability="c", provider="p", params={"prompt": "kırmızı ayakkabı"})
    with Image.open(sample_png) as img:
        img.load()
        info = PngImagePlugin.PngInfo()
        info.add_itxt("ai-provenance", provenance.to_json(), zip=False)
        pixel = img.copy()
    pixel.save(sample_png, pnginfo=info)
    assert extract_png(sample_png) == provenance


def test_embed_does_not_leave_a_temp_file_on_failure(sample_png: Path, monkeypatch):
    import os

    def failing_replace(src, dst, *args, **kwargs):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        embed_png(sample_png, Provenance(capability="c", provider="p", params={}))
    assert [p.name for p in sample_png.parent.iterdir()] == [sample_png.name]
