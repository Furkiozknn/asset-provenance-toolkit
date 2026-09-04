"""Embed/extract provenance in a JPEG file's own segment structure.

Unlike the PNG backend, this never decodes or re-encodes pixel data - JPEG
recompression is lossy, so re-saving through a decode/encode round trip
(the way `png_backend` re-saves PNGs) would quietly degrade every image it
touched. Instead this module edits the *container* directly: it inserts a
custom APP1 marker segment carrying our own identifier string
(``AIPROV1\\x00``) followed by the provenance JSON, the same "namespaced
marker, foreign markers preserved" idea as the PNG tEXt backend, just at the
byte level instead of through Pillow. Note this is a private marker, not a
standard EXIF UserComment tag or an XMP packet - a generic EXIF/XMP viewer
will not surface it, only this tool's own `extract`/`aprov extract`.

JPEG structure (ITU-T T.81 Annex B): a file is SOI (0xFFD8), then a run of
marker segments (marker byte + 2-byte big-endian length, the length
covering itself and the payload but not the marker), until SOS (0xFFDA)
starts the entropy-coded scan data. Everything from SOS to EOI (0xFFD9,
possibly with more SOS/scan pairs in progressive JPEGs) is left completely
untouched here - only the pre-SOS marker segments are inspected or edited.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .schema import Provenance

_SOI = b"\xff\xd8"
_APP0 = 0xE0
_APP1 = 0xE1
_SOS = 0xDA
_EOI = 0xD9
#: Markers with no length field / payload of their own.
_STANDALONE = {0x01} | set(range(0xD0, 0xD8)) | {0xD8, _EOI}

#: Identifies our segment among any other APP1 users (EXIF conventionally
#: uses b"Exif\x00\x00", XMP a URI string) - namespaced the same way the PNG
#: backend's tEXt keyword is, so this tool never collides with or clobbers
#: another tool's APP1 data.
_IDENTIFIER = b"AIPROV1\x00"

#: A single marker segment's length is a 2-byte field covering itself, so
#: the identifier + payload cannot exceed this.
_MAX_PAYLOAD = 0xFFFF - 2 - len(_IDENTIFIER)


class UnreadableJpegError(Exception):
    """Raised for a read-phase failure: not a JPEG at all, or a truncated/
    malformed marker structure this parser can't safely walk."""


class JpegPayloadTooLargeError(Exception):
    """Raised when a provenance record's JSON is too large to fit in a
    single JPEG marker segment (max ~64 KB minus a small identifier
    overhead). Splitting a record across multiple segments is possible but
    deliberately not implemented - if you're hitting this, the sidecar
    backend (any extension outside the native list) has no such limit."""


def _read_segments(data: bytes, path: str | Path) -> tuple[list[tuple[int, bytes]], int]:
    """Parse `data` into (marker, raw_segment_bytes) pairs for everything
    between SOI and the first SOS, plus the byte offset where that SOS
    segment begins. Raises UnreadableJpegError on anything that doesn't
    parse as a well-formed JPEG marker sequence."""
    if not data.startswith(_SOI):
        raise UnreadableJpegError(f"{path}: not a readable JPEG file (missing SOI marker)")

    segments: list[tuple[int, bytes]] = []
    offset = 2
    while True:
        if offset + 1 >= len(data):
            raise UnreadableJpegError(f"{path}: not a readable JPEG file (truncated before SOS)")
        if data[offset] != 0xFF:
            raise UnreadableJpegError(
                f"{path}: not a readable JPEG file (expected marker at byte {offset})"
            )
        marker = data[offset + 1]
        if marker in _STANDALONE:
            segments.append((marker, data[offset : offset + 2]))
            offset += 2
            if marker == _EOI:
                raise UnreadableJpegError(f"{path}: not a readable JPEG file (hit EOI before SOS)")
            continue

        if offset + 4 > len(data):
            raise UnreadableJpegError(f"{path}: not a readable JPEG file (truncated marker length)")
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        seg_end = offset + 2 + length
        if length < 2 or seg_end > len(data):
            raise UnreadableJpegError(f"{path}: not a readable JPEG file (invalid segment length)")

        segments.append((marker, data[offset:seg_end]))
        offset = seg_end
        if marker == _SOS:
            return segments, offset


def _our_segment(provenance: Provenance) -> bytes:
    payload = _IDENTIFIER + provenance.to_json().encode("utf-8")
    if len(payload) > _MAX_PAYLOAD:
        raise JpegPayloadTooLargeError(
            f"provenance JSON ({len(payload)} bytes) exceeds the {_MAX_PAYLOAD}-byte limit "
            "of a single JPEG marker segment; use the sidecar backend for records this large "
            "(rename/copy the asset to a non-native extension, or embed a smaller `result`)"
        )
    length = len(payload) + 2
    return bytes([0xFF, _APP1]) + length.to_bytes(2, "big") + payload


def _is_ours(marker: int, raw: bytes) -> bool:
    return marker == _APP1 and raw[4 : 4 + len(_IDENTIFIER)] == _IDENTIFIER


def _rebuild(
    data: bytes, path: str | Path, *, new_segment: Optional[bytes]
) -> bytes:
    segments, sos_start = _read_segments(data, path)

    # Insert (or re-insert) right after any leading APP0/JFIF segment, so a
    # JFIF marker required to be first stays first - everything else keeps
    # its relative order.
    insert_at = 0
    while insert_at < len(segments) and segments[insert_at][0] == _APP0:
        insert_at += 1

    kept = [(m, r) for m, r in segments if not _is_ours(m, r)]
    if new_segment is not None:
        kept = kept[:insert_at] + [(_APP1, new_segment)] + kept[insert_at:]

    body = b"".join(raw for _, raw in kept)
    return _SOI + body + data[sos_start:]


def embed_jpeg(path: str | Path, provenance: Provenance) -> None:
    """Insert (replacing any stale copy of) our provenance segment into the
    JPEG at `path`. Every byte outside that one segment - including all
    scan/pixel data - is preserved exactly."""
    data = Path(path).read_bytes()
    new_data = _rebuild(data, path, new_segment=_our_segment(provenance))
    Path(path).write_bytes(new_data)


def extract_jpeg(path: str | Path) -> Optional[Provenance]:
    data = Path(path).read_bytes()
    segments, _ = _read_segments(data, path)
    for marker, raw in segments:
        if _is_ours(marker, raw):
            raw_json = raw[4 + len(_IDENTIFIER) :].decode("utf-8")
            return Provenance.from_json(raw_json)
    return None


def strip_jpeg(path: str | Path) -> bool:
    """Remove our provenance segment, leaving every other byte untouched.
    Returns False (no-op) if there was nothing to remove."""
    data = Path(path).read_bytes()
    segments, _ = _read_segments(data, path)
    if not any(_is_ours(m, r) for m, r in segments):
        return False
    new_data = _rebuild(data, path, new_segment=None)
    Path(path).write_bytes(new_data)
    return True
