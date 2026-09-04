from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from asset_provenance_toolkit.jpeg_backend import (
    JpegPayloadTooLargeError,
    UnreadableJpegError,
    embed_jpeg,
    extract_jpeg,
    strip_jpeg,
)
from asset_provenance_toolkit.schema import Provenance


def test_extract_returns_none_when_nothing_embedded(sample_jpg: Path):
    assert extract_jpeg(sample_jpg) is None


def test_embed_then_extract_roundtrips(sample_jpg: Path):
    provenance = Provenance(capability="mock-generate", provider="mock", params={"prompt": "a cat"})
    embed_jpeg(sample_jpg, provenance)
    assert extract_jpeg(sample_jpg) == provenance


def test_embed_does_not_touch_scan_data_bytes(sample_jpg: Path):
    # Unlike the PNG backend (which re-encodes losslessly), the JPEG backend
    # must not decode/re-encode at all - any recompression would be lossy.
    # Prove it by checking the compressed scan bytes are byte-identical,
    # not just that decoded pixels look close.
    original = sample_jpg.read_bytes()
    sos_index = original.index(b"\xff\xda")
    original_scan_tail = original[sos_index:]

    embed_jpeg(sample_jpg, Provenance(capability="c", provider="p", params={}))

    after = sample_jpg.read_bytes()
    after_sos_index = after.index(b"\xff\xda")
    assert after[after_sos_index:] == original_scan_tail


def test_embed_preserves_other_app_segments(sample_jpg: Path):
    # Simulate another tool's APP1 (e.g. real EXIF) already being present.
    other_segment = b"\xff\xe1" + (2 + 10).to_bytes(2, "big") + b"Exif\x00\x00abcd"
    data = sample_jpg.read_bytes()
    patched = data[:2] + other_segment + data[2:]
    sample_jpg.write_bytes(patched)

    embed_jpeg(sample_jpg, Provenance(capability="c", provider="p", params={}))

    assert other_segment in sample_jpg.read_bytes()
    assert extract_jpeg(sample_jpg) is not None


def test_re_embed_replaces_stale_provenance_not_duplicates_it(sample_jpg: Path):
    embed_jpeg(sample_jpg, Provenance(capability="first", provider="p", params={}))
    embed_jpeg(sample_jpg, Provenance(capability="second", provider="p", params={}))
    assert extract_jpeg(sample_jpg).capability == "second"
    # Only one of our segments should be present.
    data = sample_jpg.read_bytes()
    assert data.count(b"AIPROV1\x00") == 1


def test_strip_removes_provenance_and_reports_true(sample_jpg: Path):
    embed_jpeg(sample_jpg, Provenance(capability="c", provider="p", params={}))
    assert strip_jpeg(sample_jpg) is True
    assert extract_jpeg(sample_jpg) is None


def test_strip_on_file_with_no_provenance_is_a_noop_reporting_false(sample_jpg: Path):
    assert strip_jpeg(sample_jpg) is False


def test_strip_preserves_other_app_segments(sample_jpg: Path):
    other_segment = b"\xff\xe1" + (2 + 10).to_bytes(2, "big") + b"Exif\x00\x00abcd"
    data = sample_jpg.read_bytes()
    patched = data[:2] + other_segment + data[2:]
    sample_jpg.write_bytes(patched)
    embed_jpeg(sample_jpg, Provenance(capability="c", provider="p", params={}))

    strip_jpeg(sample_jpg)

    assert other_segment in sample_jpg.read_bytes()


def test_decoded_pixels_unaffected_by_embed_and_strip(sample_jpg: Path):
    with Image.open(sample_jpg) as before:
        before_pixels = list(before.convert("RGB").getdata())

    embed_jpeg(sample_jpg, Provenance(capability="c", provider="p", params={}))
    strip_jpeg(sample_jpg)

    with Image.open(sample_jpg) as after:
        after_pixels = list(after.convert("RGB").getdata())
    assert before_pixels == after_pixels


def test_extract_raises_on_non_jpeg_file(tmp_path: Path):
    fake = tmp_path / "fake.jpg"
    fake.write_bytes(b"not actually a jpeg")
    with pytest.raises(UnreadableJpegError, match="not a readable JPEG"):
        extract_jpeg(fake)


def test_extract_raises_on_truncated_jpeg(sample_jpg: Path):
    truncated = sample_jpg.read_bytes()[:10]
    sample_jpg.write_bytes(truncated)
    with pytest.raises(UnreadableJpegError):
        extract_jpeg(sample_jpg)


def test_embed_raises_clean_error_when_payload_too_large(sample_jpg: Path):
    huge_params = {"prompt": "x" * 100_000}
    with pytest.raises(JpegPayloadTooLargeError, match="exceeds"):
        embed_jpeg(sample_jpg, Provenance(capability="c", provider="p", params=huge_params))
