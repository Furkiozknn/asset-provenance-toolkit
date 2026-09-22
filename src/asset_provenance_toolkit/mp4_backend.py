"""Embed/extract provenance in an MP4 / QuickTime file's own box structure.

Video is where a sidecar hurts most. A generated clip is the asset most
likely to leave the system that made it as a single file - uploaded,
re-shared, dropped into an edit - and a `.provenance.json` sitting next to
it does not survive any of that. So this backend does for ISO base media
files what `jpeg_backend` does for JPEG: it edits the *container* and never
touches a single byte of media data.

ISO/IEC 14496-12 structure: a file is a flat sequence of boxes, each a
4-byte big-endian size followed by a 4-byte type. A size of 1 means the
real size is in the 8 bytes that follow (`largesize`); a size of 0 means
"to the end of the file" and is only legal on the last box. The record goes
into a `uuid` box - the format's own extension point for private data,
which is exactly how XMP is carried in MP4 - tagged with a UUID belonging
to this tool, so a foreign `uuid` box (XMP's, a camera vendor's) is never
read as ours and never overwritten.

THE RULE THAT SHAPES THIS WHOLE MODULE
--------------------------------------
`stco`/`co64` inside `moov` store **absolute file offsets** into `mdat`.
Insert a box anywhere before the end of `mdat` and every one of those
offsets is silently wrong: the file still parses, still reports the right
duration, and plays as garbage or not at all. This is the trap that makes
naive metadata injection corrupt video, and it is why the JPEG approach
(splice a segment in near the front) cannot be reused here.

So the invariant is mechanical: **no byte at or before the end of the last
`mdat` ever moves.** Our box is appended at the end of the file, and any
edit that would have to relocate something inside the protected region is
refused with `UnsafeMp4EditError` rather than performed. Everything past
that point - a trailing `moov` in a non-faststart file, a `free` box - may
shift freely, because nothing points at it by absolute offset.

Two details fall out of that rule:

* If the final box is `mfra`, the random-access index of a fragmented file,
  our box is inserted *before* it. `mfra` is required to be last (a reader
  finds it by seeking to the end and reading `mfro`), and its contents are
  offsets to `moof` boxes that live before the protected boundary, so
  moving `mfra` itself is harmless while appending after it is not.
* A trailing box declared with size 0 would swallow anything appended after
  it, so its size field is rewritten to its real length. That is a 4-byte
  in-place edit in a field that already exists - it shifts nothing.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .schema import Provenance

#: This tool's own `uuid` box identifier. Randomly generated once and frozen:
#: a UUID is the format's namespacing mechanism, so a collision with XMP
#: (be7acfcb-97a9-42e8-9c71-999491e3afac) or any vendor box is impossible
#: rather than merely unlikely.
PROVENANCE_UUID = _uuid.UUID("34b18cdb-71a0-439a-918b-18ed1f2ecafc")
_UUID_BYTES = PROVENANCE_UUID.bytes

_BOX_HEADER = 8
_LARGE_HEADER = 16
_UUID_HEADER = _BOX_HEADER + 16
_MAX_32 = 0xFFFFFFFF

#: Boxes whose bytes are addressed by absolute offset from elsewhere in the
#: file. `mdat` is the one that matters in practice; `idat` is its item-data
#: counterpart in HEIF-style files, addressed the same way.
_MEDIA_BOXES = {b"mdat", b"idat"}


class UnreadableMp4Error(Exception):
    """Raised for a read-phase failure: not an ISO base media file at all,
    or a box structure this parser cannot safely walk (truncated download,
    a file of some other type renamed to `.mp4`, ...)."""


class UnsafeMp4EditError(Exception):
    """Raised when the edit could only be done by moving bytes that media
    offsets point at - which would produce a file that still parses but no
    longer plays. Refusing is the only honest outcome: there is no way to
    remove those bytes here without rewriting `stco`/`co64`, and a tool that
    quietly corrupts video is worse than one that declines."""


@dataclass(frozen=True)
class _Box:
    type: bytes
    start: int
    end: int
    header: int
    #: True when the box declared size 0 ("to end of file"), which has to be
    #: rewritten to a real length before anything can follow it.
    open_ended: bool

    @property
    def payload_start(self) -> int:
        return self.start + self.header


def _walk(data: bytes, path: str | Path) -> list[_Box]:
    """Parse the flat top-level box sequence. Raises UnreadableMp4Error on
    anything that does not account for the whole file exactly - a partial
    parse is how a corrupt file gets silently half-edited."""
    boxes: list[_Box] = []
    offset = 0
    total = len(data)
    while offset < total:
        if offset + _BOX_HEADER > total:
            raise UnreadableMp4Error(
                f"{path}: not a readable MP4/QuickTime file "
                f"(truncated box header at byte {offset})"
            )
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8]
        header = _BOX_HEADER
        open_ended = False

        if size == 1:
            if offset + _LARGE_HEADER > total:
                raise UnreadableMp4Error(
                    f"{path}: not a readable MP4/QuickTime file "
                    f"(truncated 64-bit box size at byte {offset})"
                )
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header = _LARGE_HEADER
        elif size == 0:
            size = total - offset
            open_ended = True

        if size < header or offset + size > total:
            raise UnreadableMp4Error(
                f"{path}: not a readable MP4/QuickTime file "
                f"(box {box_type!r} at byte {offset} declares an impossible size)"
            )
        boxes.append(_Box(box_type, offset, offset + size, header, open_ended))
        offset += size

    if not boxes:
        raise UnreadableMp4Error(f"{path}: not a readable MP4/QuickTime file (empty file)")
    types = {b.type for b in boxes}
    if not (b"ftyp" in types or b"moov" in types):
        raise UnreadableMp4Error(
            f"{path}: not a readable MP4/QuickTime file (no ftyp or moov box at the top level)"
        )
    return boxes


def _is_ours(data: bytes, box: _Box) -> bool:
    if box.type != b"uuid":
        return False
    return data[box.payload_start : box.payload_start + 16] == _UUID_BYTES


def _guard_offset(boxes: list[_Box]) -> int:
    """The end of the last media box: the point up to which nothing may move,
    because `stco`/`co64` entries are absolute offsets into it."""
    ends = [b.end for b in boxes if b.type in _MEDIA_BOXES]
    return max(ends) if ends else 0


def _our_box(provenance: Provenance) -> bytes:
    payload = provenance.to_json().encode("utf-8")
    size = _UUID_HEADER + len(payload)
    if size > _MAX_32:
        # Not reachable with any sane record; a 64-bit header would be the
        # fix, and saying so beats a silent overflow.
        raise UnsafeMp4EditError(
            f"provenance JSON ({len(payload)} bytes) does not fit in a 32-bit box header"
        )
    return size.to_bytes(4, "big") + b"uuid" + _UUID_BYTES + payload


def _emit(data: bytes, box: _Box, path: str | Path) -> bytes:
    """A box's bytes, with a size-0 header rewritten to its real length so
    something can legally follow it. The rewrite lands in the 4-byte field
    that is already there, so no byte moves."""
    raw = data[box.start : box.end]
    if not box.open_ended:
        return raw
    real = box.end - box.start
    if real > _MAX_32:
        raise UnsafeMp4EditError(
            f"{path}: the final box {box.type.decode('latin1')!r} is open-ended and larger than "
            "4 GiB; closing it would need a 64-bit header, which would shift media data"
        )
    return real.to_bytes(4, "big") + raw[4:]


def _rebuild(data: bytes, path: str | Path, *, new_box: Optional[bytes]) -> bytes:
    boxes = _walk(data, path)
    guard = _guard_offset(boxes)

    stale = [b for b in boxes if _is_ours(data, b)]
    trapped = [b for b in stale if b.start < guard]
    if trapped:
        raise UnsafeMp4EditError(
            f"{path}: a provenance box sits at byte {trapped[0].start}, before the end of the "
            f"media data at byte {guard}; removing it would shift every chunk offset in moov "
            "and leave a file that parses but does not play"
        )

    kept = [b for b in boxes if b not in stale]

    # `mfra` has to stay last: a reader finds it by seeking to the end of the
    # file. Its own contents point at `moof` boxes below the guard, which do
    # not move, so displacing `mfra` itself costs nothing.
    tail: list[_Box] = []
    if kept and kept[-1].type == b"mfra":
        tail = [kept.pop()]

    pieces = [_emit(data, b, path) for b in kept]
    if new_box is not None:
        pieces.append(new_box)
    pieces.extend(_emit(data, b, path) for b in tail)
    return b"".join(pieces)


def embed_mp4(path: str | Path, provenance: Provenance) -> None:
    """Append (replacing any stale copy of) our provenance box to the MP4 at
    `path`. Every byte of media data keeps its exact file offset."""
    data = Path(path).read_bytes()
    new_data = _rebuild(data, path, new_box=_our_box(provenance))
    Path(path).write_bytes(new_data)


def extract_mp4(path: str | Path) -> Optional[Provenance]:
    data = Path(path).read_bytes()
    for box in _walk(data, path):
        if _is_ours(data, box):
            raw_json = data[box.payload_start + 16 : box.end].decode("utf-8")
            return Provenance.from_json(raw_json)
    return None


def strip_mp4(path: str | Path) -> bool:
    """Remove our provenance box, leaving media data at its original offsets.
    Returns False (no-op) if there was nothing to remove."""
    data = Path(path).read_bytes()
    boxes = _walk(data, path)
    if not any(_is_ours(data, b) for b in boxes):
        return False
    new_data = _rebuild(data, path, new_box=None)
    Path(path).write_bytes(new_data)
    return True
