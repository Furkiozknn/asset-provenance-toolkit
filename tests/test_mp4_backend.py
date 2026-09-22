"""The MP4 backend, and mostly one question: did the media data move?

A metadata writer that corrupts video does not corrupt it loudly. The file
still has a valid box structure, `ffprobe` still reports the right duration
and codec, and only a decoder notices that every chunk offset in `stco` now
points ten bytes into the middle of a NAL unit. So the tests that matter
here are not "does the record round-trip" - they are the ones that pin the
byte offsets of `mdat` and the value `stco` holds.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from asset_provenance_toolkit.mp4_backend import (
    PROVENANCE_UUID,
    UnreadableMp4Error,
    UnsafeMp4EditError,
    _our_box,
    _walk,
    embed_mp4,
    extract_mp4,
    strip_mp4,
)
from asset_provenance_toolkit.schema import Provenance

from conftest import FTYP, box, build_mp4

#: XMP's `uuid` box identifier - a real, standardised user of the same
#: extension point, and therefore the thing we must never mistake for ours.
XMP_UUID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")


def _boxes(path: Path):
    return [(b.type.decode("latin1"), b.start, b.end) for b in _walk(path.read_bytes(), path)]


def _mdat_span(path: Path) -> tuple[int, int]:
    for name, start, end in _boxes(path):
        if name == "mdat":
            return start, end
    raise AssertionError("no mdat box")


def _stco_offset(data: bytes) -> int:
    """The single absolute chunk offset the fixture's sample table records."""
    i = data.index(b"stco")
    return struct.unpack(">I", data[i + 12 : i + 16])[0]


def _prov(**kw) -> Provenance:
    """A fixed record. `created_at` is pinned rather than left to default,
    so two calls compare equal and a round-trip assertion tests the
    round-trip instead of the clock."""
    kw.setdefault("capability", "video-generate")
    kw.setdefault("provider", "mock-video")
    kw.setdefault("params", {"prompt": "a red sneaker rotating", "seed": 42})
    kw.setdefault("created_at", "2026-09-02T12:00:00+00:00")
    return Provenance(**kw)


# --------------------------------------------------------------------------
# the basics
# --------------------------------------------------------------------------


def test_extract_returns_none_when_nothing_embedded(sample_mp4: Path):
    assert extract_mp4(sample_mp4) is None


@pytest.mark.parametrize("fixture", ["sample_mp4", "sample_mp4_faststart"])
def test_embed_then_extract_roundtrips(fixture, request):
    path = request.getfixturevalue(fixture)
    provenance = _prov()
    embed_mp4(path, provenance)
    assert extract_mp4(path) == provenance


def test_re_embed_replaces_stale_provenance_not_duplicates_it(sample_mp4: Path):
    embed_mp4(sample_mp4, _prov(capability="first"))
    embed_mp4(sample_mp4, _prov(capability="second"))
    assert extract_mp4(sample_mp4).capability == "second"
    assert sum(1 for name, _, _ in _boxes(sample_mp4) if name == "uuid") == 1


def test_strip_restores_the_original_file_byte_for_byte(sample_mp4: Path):
    original = sample_mp4.read_bytes()
    embed_mp4(sample_mp4, _prov())
    assert sample_mp4.read_bytes() != original
    assert strip_mp4(sample_mp4) is True
    assert sample_mp4.read_bytes() == original


def test_strip_with_nothing_embedded_is_a_noop_reporting_false(sample_mp4: Path):
    original = sample_mp4.read_bytes()
    assert strip_mp4(sample_mp4) is False
    assert sample_mp4.read_bytes() == original


# --------------------------------------------------------------------------
# the part that actually matters: media data must not move
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["sample_mp4", "sample_mp4_faststart"])
def test_embed_leaves_mdat_at_exactly_the_same_offset(fixture, request):
    path = request.getfixturevalue(fixture)
    before = _mdat_span(path)
    before_bytes = path.read_bytes()[before[0] : before[1]]

    embed_mp4(path, _prov())

    after = _mdat_span(path)
    assert after == before, "mdat moved; every chunk offset in moov is now wrong"
    assert path.read_bytes()[after[0] : after[1]] == before_bytes


@pytest.mark.parametrize("fixture", ["sample_mp4", "sample_mp4_faststart"])
def test_the_chunk_offset_in_stco_still_points_at_the_same_media_bytes(fixture, request):
    """The strongest form of the claim: follow the offset the sample table
    records and check the bytes under it are unchanged. This is what a
    decoder does, and what a structural check alone would miss."""
    path = request.getfixturevalue(fixture)
    original = path.read_bytes()
    offset = _stco_offset(original)
    pointed_at = original[offset : offset + 32]

    embed_mp4(path, _prov())

    after = path.read_bytes()
    assert _stco_offset(after) == offset, "the fixture's stco value itself changed"
    assert after[offset : offset + 32] == pointed_at


def test_our_box_is_appended_after_everything_else(sample_mp4: Path):
    embed_mp4(sample_mp4, _prov())
    names = [name for name, _, _ in _boxes(sample_mp4)]
    assert names[-1] == "uuid"


def test_strip_refuses_when_our_box_sits_before_the_media_data(sample_mp4: Path):
    """A file that some other tool (or an earlier, wronger version of this
    one) left with a provenance box in front of `mdat`. Removing it would
    shift media data back into alignment for this file but is exactly the
    class of edit this module refuses to perform blind - and the error has
    to name why."""
    data = sample_mp4.read_bytes()
    sample_mp4.write_bytes(data[: len(FTYP)] + _our_box(_prov()) + data[len(FTYP) :])

    with pytest.raises(UnsafeMp4EditError) as exc:
        strip_mp4(sample_mp4)
    assert "does not play" in str(exc.value)


def test_embed_also_refuses_rather_than_relocating_a_trapped_box(sample_mp4: Path):
    data = sample_mp4.read_bytes()
    sample_mp4.write_bytes(data[: len(FTYP)] + _our_box(_prov()) + data[len(FTYP) :])
    with pytest.raises(UnsafeMp4EditError):
        embed_mp4(sample_mp4, _prov(capability="second"))


# --------------------------------------------------------------------------
# living alongside other tools
# --------------------------------------------------------------------------


def test_a_foreign_uuid_box_is_not_read_as_ours(tmp_path: Path):
    path = tmp_path / "xmp.mp4"
    path.write_bytes(build_mp4(faststart=False) + box(b"uuid", XMP_UUID + b"<x:xmpmeta/>"))
    assert extract_mp4(path) is None


def test_a_foreign_uuid_box_survives_embed_and_strip(tmp_path: Path):
    path = tmp_path / "xmp.mp4"
    foreign = box(b"uuid", XMP_UUID + b"<x:xmpmeta/>")
    path.write_bytes(build_mp4(faststart=False) + foreign)

    embed_mp4(path, _prov())
    assert foreign in path.read_bytes()
    assert extract_mp4(path) is not None

    strip_mp4(path)
    assert foreign in path.read_bytes()
    assert extract_mp4(path) is None


def test_our_uuid_is_not_the_xmp_one():
    assert PROVENANCE_UUID.bytes != XMP_UUID


# --------------------------------------------------------------------------
# structural edge cases
# --------------------------------------------------------------------------


def test_a_trailing_open_ended_box_is_closed_before_anything_follows_it(tmp_path: Path):
    """A box declared with size 0 runs to the end of the file. Appending
    after one without rewriting its size would make it swallow our box - the
    file would still parse, and `extract` would find nothing."""
    path = tmp_path / "open.mp4"
    tail = b"trailing-free-space"
    path.write_bytes(build_mp4(faststart=True) + struct.pack(">I", 0) + b"free" + tail)

    embed_mp4(path, _prov())

    names = [name for name, _, _ in _boxes(path)]
    assert names[-2:] == ["free", "uuid"]
    assert extract_mp4(path) == _prov()


def test_mfra_stays_the_last_box(tmp_path: Path):
    """`mfra` is found by seeking to the end of the file, so it has to remain
    last; our box goes in front of it instead of after."""
    path = tmp_path / "frag.mp4"
    mfra = box(b"mfra", box(b"mfro", struct.pack(">II", 0, 24)))
    path.write_bytes(build_mp4(faststart=True) + mfra)

    embed_mp4(path, _prov())

    names = [name for name, _, _ in _boxes(path)]
    assert names[-2:] == ["uuid", "mfra"]
    assert extract_mp4(path) == _prov()
    assert mfra in path.read_bytes()


def test_a_64_bit_largesize_box_is_walked_correctly(tmp_path: Path):
    path = tmp_path / "large.mp4"
    payload = b"x" * 40
    large = struct.pack(">I", 1) + b"free" + struct.pack(">Q", 16 + len(payload)) + payload
    path.write_bytes(build_mp4(faststart=True) + large)

    embed_mp4(path, _prov())

    names = [name for name, _, _ in _boxes(path)]
    assert names == ["ftyp", "moov", "mdat", "free", "uuid"]
    assert extract_mp4(path) == _prov()


# --------------------------------------------------------------------------
# refusing to guess
# --------------------------------------------------------------------------


def test_a_file_that_is_not_iso_base_media_is_rejected(tmp_path: Path):
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"not a real mp4, just bytes pretending to be one")
    with pytest.raises(UnreadableMp4Error):
        extract_mp4(path)


def test_an_empty_file_is_rejected(tmp_path: Path):
    path = tmp_path / "empty.mp4"
    path.write_bytes(b"")
    with pytest.raises(UnreadableMp4Error):
        extract_mp4(path)


def test_a_truncated_box_is_rejected_rather_than_half_parsed(tmp_path: Path):
    path = tmp_path / "cut.mp4"
    path.write_bytes(build_mp4(faststart=True)[:-20])
    with pytest.raises(UnreadableMp4Error):
        extract_mp4(path)


def test_a_box_declaring_an_impossible_size_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.mp4"
    path.write_bytes(FTYP + struct.pack(">I", 4) + b"moov")
    with pytest.raises(UnreadableMp4Error):
        extract_mp4(path)


def test_well_formed_boxes_with_no_ftyp_or_moov_are_rejected(tmp_path: Path):
    """Parsing cleanly is not the same as being a media file - a run of
    plausible-looking boxes with no ftyp and no moov is something else."""
    path = tmp_path / "other.mp4"
    path.write_bytes(box(b"free", b"a" * 16) + box(b"skip", b"b" * 16))
    with pytest.raises(UnreadableMp4Error):
        extract_mp4(path)


def test_an_old_quicktime_file_with_moov_but_no_ftyp_is_accepted(tmp_path: Path):
    """QuickTime predates `ftyp`; a `.mov` can legitimately start with
    `moov`. Requiring `ftyp` would reject those for no reason."""
    path = tmp_path / "old.mov"
    body = build_mp4(faststart=True)[len(FTYP) :]
    path.write_bytes(body)
    embed_mp4(path, _prov())
    assert extract_mp4(path) == _prov()


# --------------------------------------------------------------------------
# negative control
# --------------------------------------------------------------------------


def test_a_naive_insert_before_mdat_would_invalidate_the_chunk_offset(sample_mp4: Path):
    """Why this backend appends instead of splicing.

    The JPEG backend puts its segment near the front of the file, which is
    correct there and catastrophic here. This does exactly that to an MP4
    and shows the damage: the offset in `stco` is untouched, the file still
    walks as a clean box structure, and the bytes it points at are no longer
    the ones it was written for. (On a real encoded clip the same edit makes
    `ffmpeg` fail on the first frame with `Invalid NAL unit size` while
    `ffprobe` still reports the right codec and duration - the structure
    survives, the video does not.)
    """
    original = sample_mp4.read_bytes()
    offset = _stco_offset(original)
    pointed_at = original[offset : offset + 32]

    spliced = original[: len(FTYP)] + _our_box(_prov()) + original[len(FTYP) :]
    sample_mp4.write_bytes(spliced)

    assert _walk(spliced, sample_mp4), "the damaged file still parses - that is the point"
    assert _stco_offset(spliced) == offset
    assert spliced[offset : offset + 32] != pointed_at

    # And the real path, on the same file, does not.
    sample_mp4.write_bytes(original)
    embed_mp4(sample_mp4, _prov())
    after = sample_mp4.read_bytes()
    assert after[offset : offset + 32] == pointed_at
