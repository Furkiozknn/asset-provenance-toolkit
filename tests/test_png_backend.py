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
    def failing_save(self, *args, **kwargs):
        raise PermissionError("permission denied (simulated)")

    monkeypatch.setattr(Image.Image, "save", failing_save)

    with pytest.raises(PermissionError):
        embed_png(sample_png, Provenance(capability="c", provider="p", params={}))


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
