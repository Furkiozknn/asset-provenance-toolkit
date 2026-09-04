"""Embed/extract provenance in a PNG's own text chunk, at the chunk level.

This is the AUTOMATIC1111 "drag the image back in to see how it was made"
pattern, generalized to be provider-agnostic: the provenance JSON lives in
the pixel file itself, so the asset stays fully self-describing wherever it
travels - no database, no sidecar required for this format.

The file is edited as a sequence of PNG chunks, never decoded. Earlier
versions re-saved through Pillow, which decodes and re-encodes every pixel:
1.3 s for a 27 MB image, and the IDAT bytes came back different - same
pixels, different compression, so a byte-level checksum of the original
encoder's output no longer matched. Splicing one chunk in before IEND is a
copy of the file plus a few hundred bytes, and leaves every other chunk,
IDAT included, byte-for-byte as it was. That is also what the JPEG backend
already does with its APP1 segment.
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .schema import Provenance

#: PNG tEXt/zTXt/iTXt keyword this tool reads/writes. Keywords are
#: conventionally short and namespaced to avoid colliding with other tools'.
PROVENANCE_KEY = "ai-provenance"

#: Above this many bytes of provenance JSON, write a compressed zTXt chunk
#: instead of an uncompressed tEXt one - the same tradeoff ComfyUI makes for
#: its embedded workflow JSON. A `result` blob (e.g. a preview or a longer
#: params dict) can otherwise bloat the PNG well past the pixel data itself;
#: Pillow decompresses zTXt transparently, so `img.text` and this module's
#: own reads see no difference either way.
_ZTXT_THRESHOLD = 2048

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TEXT_TYPES = (b"tEXt", b"zTXt", b"iTXt")


class UnreadablePngError(Exception):
    """Raised only for a read-phase failure (the file is not a PNG, or its
    chunk structure is broken) - deliberately never raised for a write-phase
    failure (permission denied, disk full, ...), which is a different problem
    with a different fix and must not be mislabeled as this one."""


# --- chunk-level reading -----------------------------------------------------

def _read_chunks(path: str | Path) -> Tuple[bytes, List[Tuple[bytes, bytes]]]:
    """Return ``(raw_file, [(type, data), ...])`` or raise UnreadablePngError.

    The whole file is read once. Every chunk's declared length must fit, IHDR
    must come first and IEND last, and the CRC of each *text* chunk is
    checked (a corrupted provenance chunk should fail loudly, not decode to
    garbage). Pixel chunks are not CRC-checked - this tool never decodes them
    and has no business being slower than a copy on their account.
    """
    path = Path(path)
    raw = path.read_bytes()  # FileNotFoundError propagates: a missing file is not an unreadable PNG
    if not raw.startswith(_SIGNATURE):
        raise UnreadablePngError(f"{path}: not a readable PNG file (bad signature)")
    chunks: List[Tuple[bytes, bytes]] = []
    offset = len(_SIGNATURE)
    total = len(raw)
    while offset < total:
        if offset + 8 > total:
            raise UnreadablePngError(f"{path}: not a readable PNG file (truncated chunk header)")
        (length,) = struct.unpack(">I", raw[offset : offset + 4])
        ctype = raw[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > total:
            raise UnreadablePngError(f"{path}: not a readable PNG file (chunk {ctype!r} runs past end of file)")
        data = raw[start:end]
        if ctype in _TEXT_TYPES:
            (crc,) = struct.unpack(">I", raw[end : end + 4])
            if crc != (zlib.crc32(ctype + data) & 0xFFFFFFFF):
                raise UnreadablePngError(f"{path}: not a readable PNG file (bad CRC on {ctype.decode('latin-1')} chunk)")
        chunks.append((ctype, data))
        offset = end + 4
        if ctype == b"IEND":
            break
    if not chunks or chunks[0][0] != b"IHDR":
        raise UnreadablePngError(f"{path}: not a readable PNG file (no IHDR chunk)")
    if chunks[-1][0] != b"IEND":
        raise UnreadablePngError(f"{path}: not a readable PNG file (no IEND chunk)")
    return raw, chunks


def _decode_text_chunk(ctype: bytes, data: bytes) -> Optional[Tuple[str, str]]:
    """``(keyword, text)`` for a tEXt/zTXt/iTXt chunk, or None if malformed."""
    try:
        if ctype == b"tEXt":
            keyword, _, text = data.partition(b"\x00")
            return keyword.decode("latin-1"), text.decode("latin-1")
        if ctype == b"zTXt":
            keyword, _, rest = data.partition(b"\x00")
            if not rest or rest[0] != 0:
                return None
            return keyword.decode("latin-1"), zlib.decompress(rest[1:]).decode("latin-1")
        if ctype == b"iTXt":
            keyword, _, rest = data.partition(b"\x00")
            if len(rest) < 2:
                return None
            compressed, method = rest[0], rest[1]
            rest = rest[2:]
            _lang, _, rest = rest.partition(b"\x00")
            _translated, _, text = rest.partition(b"\x00")
            if compressed:
                if method != 0:
                    return None
                text = zlib.decompress(text)
            return keyword.decode("latin-1"), text.decode("utf-8")
    except (zlib.error, UnicodeDecodeError):
        return None
    return None


def _text_entries(chunks: List[Tuple[bytes, bytes]]) -> Iterator[Tuple[str, str]]:
    for ctype, data in chunks:
        if ctype in _TEXT_TYPES:
            decoded = _decode_text_chunk(ctype, data)
            if decoded is not None:
                yield decoded


def _chunk_keyword(ctype: bytes, data: bytes) -> Optional[str]:
    if ctype not in _TEXT_TYPES:
        return None
    keyword, _, _ = data.partition(b"\x00")
    try:
        return keyword.decode("latin-1")
    except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes anything
        return None


# --- chunk-level writing -----------------------------------------------------

def _encode_chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)


def _provenance_chunk(text: str) -> bytes:
    """tEXt for short latin-1 payloads, zTXt above the threshold, iTXt when
    the JSON is not latin-1 (never for this tool's own ASCII JSON, but the
    writer must not silently mangle a payload that is)."""
    keyword = PROVENANCE_KEY.encode("latin-1")
    try:
        latin = text.encode("latin-1")
    except UnicodeEncodeError:
        payload = text.encode("utf-8")
        if len(payload) > _ZTXT_THRESHOLD:
            return _encode_chunk(b"iTXt", keyword + b"\x00\x01\x00\x00\x00" + zlib.compress(payload))
        return _encode_chunk(b"iTXt", keyword + b"\x00\x00\x00\x00\x00" + payload)
    if len(latin) > _ZTXT_THRESHOLD:
        return _encode_chunk(b"zTXt", keyword + b"\x00\x00" + zlib.compress(latin))
    return _encode_chunk(b"tEXt", keyword + b"\x00" + latin)


def _write_atomic(path: Path, payload: bytes) -> None:
    """Write next to the target and rename into place, so a failure mid-write
    (disk full, permission denied on the directory) never leaves a truncated
    PNG where a complete one used to be."""
    tmp = path.with_name(f".{path.name}.aprov-tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _rebuild(raw: bytes, chunks: List[Tuple[bytes, bytes]], insert: Optional[bytes]) -> bytes:
    """The file with this tool's chunk(s) removed and ``insert`` (if any) placed
    just before IEND. Every other chunk is re-emitted from its original bytes."""
    out = bytearray(_SIGNATURE)
    for ctype, data in chunks:
        if _chunk_keyword(ctype, data) == PROVENANCE_KEY:
            continue
        if ctype == b"IEND" and insert is not None:
            out += insert
        out += _encode_chunk(ctype, data)
    return bytes(out)


# --- public API --------------------------------------------------------------

def embed_png(path: str | Path, provenance: Provenance) -> None:
    """Splice provenance into the PNG's text chunks, in place.

    Lossless by construction: the pixel chunks are copied, not re-encoded.
    Any other text chunk already present (e.g. from a different tool) is
    preserved; a stale copy of this tool's own key is replaced.
    """
    path = Path(path)
    raw, chunks = _read_chunks(path)
    _write_atomic(path, _rebuild(raw, chunks, _provenance_chunk(provenance.to_json())))


def extract_png(path: str | Path) -> Optional[Provenance]:
    _raw, chunks = _read_chunks(path)
    for keyword, text in _text_entries(chunks):
        if keyword == PROVENANCE_KEY:
            return Provenance.from_json(text)
    return None


def strip_png(path: str | Path) -> bool:
    """Remove this tool's provenance chunk, preserving every other chunk.
    Returns False (no-op) if there was nothing to remove."""
    path = Path(path)
    raw, chunks = _read_chunks(path)
    if not any(_chunk_keyword(ctype, data) == PROVENANCE_KEY for ctype, data in chunks):
        return False
    _write_atomic(path, _rebuild(raw, chunks, None))
    return True
