"""Dispatches to the right backend (native embedding where one exists,
sidecar JSON otherwise) based on file extension - the single entry point
the CLI and library callers use."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
from pathlib import Path
from typing import Callable, NamedTuple, Optional

from . import jpeg_backend, mp4_backend, png_backend, sidecar_backend
from .jpeg_backend import JpegPayloadTooLargeError, UnreadableJpegError
from .mp4_backend import UnreadableMp4Error, UnsafeMp4EditError
from .png_backend import UnreadablePngError
from .schema import Provenance, ProvenanceError


class _NativeBackend(NamedTuple):
    name: str
    embed: Callable[[str | Path, Provenance], None]
    extract: Callable[[str | Path], Optional[Provenance]]
    strip: Callable[[str | Path], bool]
    #: Exception type(s) this backend raises for a "clean" domain error
    #: (unreadable file, oversized payload, ...) that the CLI should report
    #: as `error: ...` rather than let escape as a raw traceback.
    clean_errors: tuple[type[Exception], ...]
    #: SHA-256 hex of the file as `strip` would leave it (see
    #: `content_digest`). None means "hash the whole file", which is only
    #: right for a backend that never writes into the file itself.
    digest: Optional[Callable[[str | Path], str]] = None


#: Extensions with a native embedding backend. Extend this (and add a new
#: `*_backend.py` module) as more native formats get support; anything not
#: listed here falls through to the universal sidecar. The ISO base media
#: family (`.mp4`, `.m4v`, `.m4a`, `.mov`) all share one box structure, so
#: they share one backend - the walker validates the structure rather than
#: trusting the extension, which is also what catches a file of some other
#: type that was renamed.
_JPEG_BACKEND = _NativeBackend(
    "jpeg",
    jpeg_backend.embed_jpeg,
    jpeg_backend.extract_jpeg,
    jpeg_backend.strip_jpeg,
    (UnreadableJpegError, JpegPayloadTooLargeError),
    jpeg_backend.content_digest_jpeg,
)
_MP4_BACKEND = _NativeBackend(
    "mp4",
    mp4_backend.embed_mp4,
    mp4_backend.extract_mp4,
    mp4_backend.strip_mp4,
    (UnreadableMp4Error, UnsafeMp4EditError),
    mp4_backend.content_digest_mp4,
)
_NATIVE_BACKENDS: dict[str, _NativeBackend] = {
    ".png": _NativeBackend(
        "png",
        png_backend.embed_png,
        png_backend.extract_png,
        png_backend.strip_png,
        (UnreadablePngError,),
        png_backend.content_digest_png,
    ),
    ".jpg": _JPEG_BACKEND,
    ".jpeg": _JPEG_BACKEND,
    ".mp4": _MP4_BACKEND,
    ".m4v": _MP4_BACKEND,
    ".m4a": _MP4_BACKEND,
    ".mov": _MP4_BACKEND,
}


def _native_backend_for(path: str | Path) -> Optional[_NativeBackend]:
    return _NATIVE_BACKENDS.get(Path(path).suffix.lower())


def _require_file(path: str | Path) -> None:
    """One check for every entry point. A directory used to pass `exists()`
    and get a `<dir>.provenance.json` sidecar - and `verify` then reported OK
    for it. Both errors are OSError subclasses, which the CLI already reports
    as `error: ...`."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    if p.is_dir():
        raise IsADirectoryError(
            f"{path} is a directory, not a file - aprov works on one file at a time "
            "(for a folder, loop over its files in your shell)"
        )


def _run(fn, backend: _NativeBackend, *args):
    """Run a backend read/write function, turning its read-phase-only error
    (wrong file renamed to this extension, truncated/corrupt download, ...)
    into a ProvenanceError - every CLI command already knows how to report
    a ProvenanceError cleanly. A write-phase failure (permission denied,
    disk full, ...) is a different problem and is deliberately left as its
    native exception type, not caught here."""
    try:
        return fn(*args)
    except backend.clean_errors as exc:
        raise ProvenanceError(str(exc)) from exc


#: Prefix of every `content_hash` this version writes and can check.
CONTENT_HASH_PREFIX = "sha256:"


def content_digest(path: str | Path) -> str:
    """``"sha256:<hex>"`` of the file's content with this tool's record left
    out: the bytes `strip` would leave behind, hashed without writing them.

    Embedding only adds the record, so the digest of a file is the same
    before and after `embed`, and changes when anything else in the file
    does: a re-encode, an edit, a different file swapped in under the same
    name. For a file whose record lives in a sidecar, it is the whole file.
    """
    _require_file(path)
    backend = _native_backend_for(path)
    if backend is not None and backend.digest is not None:
        return CONTENT_HASH_PREFIX + _run(backend.digest, backend, path)
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    return CONTENT_HASH_PREFIX + sha.hexdigest()


class ContentCheck(NamedTuple):
    """Outcome of `check_content`.

    ``status`` is ``"match"``, ``"mismatch"``, ``"unbound"`` (the record has
    no content_hash, e.g. it was written by an older version) or
    ``"unsupported"`` (a hash algorithm this version does not know).
    """

    status: str
    expected: Optional[str]
    actual: Optional[str]


def check_content(path: str | Path, provenance: Provenance) -> ContentCheck:
    """Compare the file's current `content_digest` with the one recorded in
    `provenance`. Detects change, not intent: the record is unsigned, so
    anyone can re-embed a fresh hash after editing the file."""
    expected = provenance.content_hash
    if expected is None:
        return ContentCheck("unbound", None, None)
    if not expected.startswith(CONTENT_HASH_PREFIX):
        return ContentCheck("unsupported", expected, None)
    actual = content_digest(path)
    status = "match" if hmac.compare_digest(actual, expected.lower()) else "mismatch"
    return ContentCheck(status, expected, actual)


def embed(path: str | Path, provenance: Provenance, *, bind_content: bool = False) -> str:
    """Embed `provenance` into the asset at `path`. Returns which backend
    was used ("png", "jpeg", "mp4", or "sidecar"), since callers/CLI output
    often want to say so explicitly rather than leave it implicit.

    ``bind_content=True`` first records the file's `content_digest` as the
    record's ``content_hash`` (the caller's object is not modified), so a
    later `check_content` can tell whether the file changed. The CLI does
    this by default; it costs one extra read of the file."""
    _require_file(path)
    if bind_content:
        provenance = dataclasses.replace(provenance, content_hash=content_digest(path))
    backend = _native_backend_for(path)
    if backend is not None:
        _run(backend.embed, backend, path, provenance)
        return backend.name
    sidecar_backend.embed_sidecar(path, provenance)
    return "sidecar"


def extract(path: str | Path) -> Optional[Provenance]:
    """Look for provenance on `path`: check the native backend first (if
    one applies to this extension), then always also check for a sidecar
    file - a sidecar can legitimately exist even next to an image whose
    embedded record was stripped by some other tool along the way, and
    checking costs nothing."""
    _require_file(path)
    backend = _native_backend_for(path)
    if backend is not None:
        found = _run(backend.extract, backend, path)
        if found is not None:
            return found
    return sidecar_backend.extract_sidecar(path)


def strip(path: str | Path) -> bool:
    """Remove provenance from `path`, in whichever backend(s) it's present.
    Returns True if anything was actually removed."""
    _require_file(path)
    removed = False
    backend = _native_backend_for(path)
    if backend is not None:
        removed = _run(backend.strip, backend, path) or removed
    removed = sidecar_backend.strip_sidecar(path) or removed
    return removed
