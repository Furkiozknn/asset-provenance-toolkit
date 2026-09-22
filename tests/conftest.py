from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    path = tmp_path / "sample.png"
    Image.new("RGB", (16, 16), (200, 100, 50)).save(path)
    return path


@pytest.fixture
def sample_jpg(tmp_path: Path) -> Path:
    path = tmp_path / "sample.jpg"
    Image.new("RGB", (16, 16), (50, 100, 200)).save(path, format="JPEG", quality=90)
    return path


@pytest.fixture
def sample_non_png(tmp_path: Path) -> Path:
    """A file type with no native backend, so the sidecar has to take it.

    Deliberately `.wav` and not `.mp4`: mp4 used to be the example of "we
    have no backend for this", and once `mp4_backend` existed this fixture
    would quietly have been testing the mp4 path while claiming to test the
    sidecar. Audio is the honest stand-in now - WAV is RIFF, not ISO base
    media, so it will not acquire a native backend by accident.
    """
    path = tmp_path / "sample.wav"
    path.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt not a real wav, just bytes")
    return path


# ---------------------------------------------------------------------------
# ISO base media (MP4) fixtures
#
# Built by hand rather than with ffmpeg, so the suite has no external binary
# dependency - and, more usefully, so the chunk offset in `stco` is a value
# the test itself chose and can assert on afterwards. A real encoder's file
# would prove the same thing less legibly.
# ---------------------------------------------------------------------------

#: Recognisable media payload. A test that wants to prove media data did not
#: move checks that the offset recorded in `stco` still lands on this.
MEDIA_PAYLOAD = b"CHUNK-ONE|" + bytes(range(256)) * 2 + b"|CHUNK-END"
#: Where inside the mdat payload the "first chunk" nominally starts.
CHUNK_OFFSET_IN_MDAT = 10


def box(box_type: bytes, payload: bytes) -> bytes:
    """One ISO base media box: 4-byte big-endian size (covering the header),
    4-byte type, payload."""
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def _stbl(chunk_offset: int) -> bytes:
    """A minimal sample table whose `stco` carries one absolute file offset -
    the exact thing that breaks when a naive writer shifts media data."""
    stco = box(b"stco", struct.pack(">III", 0, 1, chunk_offset))
    return box(b"stbl", stco)


def _moov(chunk_offset: int) -> bytes:
    return box(
        b"moov",
        box(b"mvhd", b"\x00" * 100)
        + box(b"trak", box(b"mdia", box(b"minf", _stbl(chunk_offset)))),
    )


FTYP = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")


def build_mp4(*, faststart: bool) -> bytes:
    """A structurally valid ISO base media file in either of the two layouts
    a real encoder produces: `moov` after `mdat` (streaming-hostile but what
    ffmpeg writes by default) or before it (`-movflags +faststart`)."""
    mdat = box(b"mdat", MEDIA_PAYLOAD)
    if not faststart:
        mdat_start = len(FTYP)
        return FTYP + mdat + _moov(mdat_start + 8 + CHUNK_OFFSET_IN_MDAT)
    moov_size = len(_moov(0))
    mdat_start = len(FTYP) + moov_size
    return FTYP + _moov(mdat_start + 8 + CHUNK_OFFSET_IN_MDAT) + mdat


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(build_mp4(faststart=False))
    return path


@pytest.fixture
def sample_mp4_faststart(tmp_path: Path) -> Path:
    path = tmp_path / "clip-faststart.mp4"
    path.write_bytes(build_mp4(faststart=True))
    return path
