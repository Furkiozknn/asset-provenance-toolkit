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

import os
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Union

from ._atomic import write_atomic_with
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

#: Largest record `extract` will read out of our box. A real record is a
#: few KB; a crafted file declaring a multi-GB box must not make a read-only
#: command allocate that much memory.
_MAX_RECORD = 16 * 1024 * 1024

#: Copy buffer for the streaming rewrite. Video files are routinely larger
#: than the memory it would be reasonable to spend on adding a few hundred
#: bytes of metadata, so nothing here ever holds the whole file.
_COPY_CHUNK = 1024 * 1024

#: Reads `n` bytes at absolute offset `o` - backed by a bytes object in the
#: tests, by a seekable file everywhere else.
_ReadAt = Callable[[int, int], bytes]

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


def _walk_with(read_at: _ReadAt, total: int, path: str | Path) -> list[_Box]:
    """Parse the flat top-level box sequence, reading only box headers.
    Raises UnreadableMp4Error on anything that does not account for the
    whole file exactly - a partial parse is how a corrupt file gets silently
    half-edited."""
    boxes: list[_Box] = []
    offset = 0
    while offset < total:
        if offset + _BOX_HEADER > total:
            raise UnreadableMp4Error(
                f"{path}: not a readable MP4/QuickTime file "
                f"(truncated box header at byte {offset})"
            )
        head = read_at(offset, _BOX_HEADER)
        size = int.from_bytes(head[:4], "big")
        box_type = head[4:8]
        header = _BOX_HEADER
        open_ended = False

        if size == 1:
            if offset + _LARGE_HEADER > total:
                raise UnreadableMp4Error(
                    f"{path}: not a readable MP4/QuickTime file "
                    f"(truncated 64-bit box size at byte {offset})"
                )
            size = int.from_bytes(read_at(offset + 8, 8), "big")
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


def _walk(data: bytes, path: str | Path) -> list[_Box]:
    """`_walk_with` over an in-memory file (used by the tests)."""
    return _walk_with(lambda o, n: data[o : o + n], len(data), path)


def _file_reader(fh: BinaryIO) -> _ReadAt:
    def read_at(offset: int, n: int) -> bytes:
        fh.seek(offset)
        return fh.read(n)

    return read_at


def _is_ours(read_at: _ReadAt, box: _Box) -> bool:
    if box.type != b"uuid":
        return False
    return read_at(box.payload_start, 16) == _UUID_BYTES


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


#: One piece of the rewritten file: literal bytes, or a (start, end) range
#: copied verbatim from the original.
_Piece = Union[bytes, tuple[int, int]]


def _emit(box: _Box, path: str | Path) -> list[_Piece]:
    """A box as pieces, with a size-0 header rewritten to its real length so
    something can legally follow it. The rewrite lands in the 4-byte field
    that is already there, so no byte moves."""
    if not box.open_ended:
        return [(box.start, box.end)]
    real = box.end - box.start
    if real > _MAX_32:
        raise UnsafeMp4EditError(
            f"{path}: the final box {box.type.decode('latin1')!r} is open-ended and larger than "
            "4 GiB; closing it would need a 64-bit header, which would shift media data"
        )
    return [real.to_bytes(4, "big"), (box.start + 4, box.end)]


def _plan(read_at: _ReadAt, total: int, path: str | Path, *, new_box: Optional[bytes]) -> list[_Piece]:
    boxes = _walk_with(read_at, total, path)
    guard = _guard_offset(boxes)

    stale = [b for b in boxes if _is_ours(read_at, b)]
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

    pieces: list[_Piece] = []
    for b in kept:
        pieces.extend(_emit(b, path))
    if new_box is not None:
        pieces.append(new_box)
    for b in tail:
        pieces.extend(_emit(b, path))
    return pieces


def _rebuild(data: bytes, path: str | Path, *, new_box: Optional[bytes]) -> bytes:
    """In-memory form of the rewrite, kept for tests and small inputs."""
    pieces = _plan(lambda o, n: data[o : o + n], len(data), path, new_box=new_box)
    return b"".join(p if isinstance(p, bytes) else data[p[0] : p[1]] for p in pieces)


def _write_pieces(src: BinaryIO, pieces: list[_Piece], dst: BinaryIO) -> None:
    for piece in pieces:
        if isinstance(piece, bytes):
            dst.write(piece)
            continue
        start, end = piece
        src.seek(start)
        remaining = end - start
        while remaining:
            chunk = src.read(min(_COPY_CHUNK, remaining))
            if not chunk:  # the file shrank under us; do not write a short copy
                raise UnreadableMp4Error("file changed size while it was being rewritten")
            dst.write(chunk)
            remaining -= len(chunk)


def _rewrite(path: str | Path, *, new_box: Optional[bytes], only_if_ours: bool) -> bool:
    with open(path, "rb") as src:
        total = os.fstat(src.fileno()).st_size
        read_at = _file_reader(src)
        if only_if_ours and not any(_is_ours(read_at, b) for b in _walk_with(read_at, total, path)):
            return False
        pieces = _plan(read_at, total, path, new_box=new_box)

    def copy(dst: BinaryIO) -> None:
        # Reopened here, and closed again before write_atomic_with renames
        # over the original: Windows refuses to replace a file that is
        # still open.
        with open(path, "rb") as again:
            _write_pieces(again, pieces, dst)

    write_atomic_with(path, copy)
    return True


def embed_mp4(path: str | Path, provenance: Provenance) -> None:
    """Append (replacing any stale copy of) our provenance box to the MP4 at
    `path`. Every byte of media data keeps its exact file offset. The file
    is streamed, never loaded whole, so memory use does not grow with it."""
    _rewrite(path, new_box=_our_box(provenance), only_if_ours=False)


def extract_mp4(path: str | Path) -> Optional[Provenance]:
    with open(path, "rb") as fh:
        total = os.fstat(fh.fileno()).st_size
        read_at = _file_reader(fh)
        for box in _walk_with(read_at, total, path):
            if _is_ours(read_at, box):
                start = box.payload_start + 16
                if box.end - start > _MAX_RECORD:
                    raise UnreadableMp4Error(
                        f"{path}: provenance box declares {box.end - start} bytes of record, "
                        f"more than the {_MAX_RECORD}-byte limit; refusing to load it"
                    )
                return Provenance.from_json(read_at(start, box.end - start))
    return None


def strip_mp4(path: str | Path) -> bool:
    """Remove our provenance box, leaving media data at its original offsets.
    Returns False (no-op) if there was nothing to remove."""
    return _rewrite(path, new_box=None, only_if_ours=True)
