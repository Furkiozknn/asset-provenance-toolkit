"""Dispatches to the right backend (native embedding where one exists,
sidecar JSON otherwise) based on file extension - the single entry point
the CLI and library callers use."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, NamedTuple, Optional

from . import jpeg_backend, png_backend, sidecar_backend
from .jpeg_backend import JpegPayloadTooLargeError, UnreadableJpegError
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


#: Extensions with a native embedding backend. Extend this (and add a new
#: `*_backend.py` module) as more native formats get support - MP4/QuickTime
#: atoms are a natural next candidate, deliberately not implemented in v1 to
#: keep the initial scope to the two most common AI-pipeline image formats
#: plus the universal sidecar fallback for everything else.
_JPEG_BACKEND = _NativeBackend(
    "jpeg",
    jpeg_backend.embed_jpeg,
    jpeg_backend.extract_jpeg,
    jpeg_backend.strip_jpeg,
    (UnreadableJpegError, JpegPayloadTooLargeError),
)
_NATIVE_BACKENDS: dict[str, _NativeBackend] = {
    ".png": _NativeBackend(
        "png", png_backend.embed_png, png_backend.extract_png, png_backend.strip_png, (UnreadablePngError,)
    ),
    ".jpg": _JPEG_BACKEND,
    ".jpeg": _JPEG_BACKEND,
}


def _native_backend_for(path: str | Path) -> Optional[_NativeBackend]:
    return _NATIVE_BACKENDS.get(Path(path).suffix.lower())


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


def embed(path: str | Path, provenance: Provenance) -> str:
    """Embed `provenance` into the asset at `path`. Returns which backend
    was used ("png", "jpeg", or "sidecar"), since callers/CLI output often
    want to say so explicitly rather than leave it implicit."""
    if not Path(path).exists():
        raise FileNotFoundError(f"no such file: {path}")
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
    if not Path(path).exists():
        raise FileNotFoundError(f"no such file: {path}")
    backend = _native_backend_for(path)
    if backend is not None:
        found = _run(backend.extract, backend, path)
        if found is not None:
            return found
    return sidecar_backend.extract_sidecar(path)


def strip(path: str | Path) -> bool:
    """Remove provenance from `path`, in whichever backend(s) it's present.
    Returns True if anything was actually removed."""
    if not Path(path).exists():
        raise FileNotFoundError(f"no such file: {path}")
    removed = False
    backend = _native_backend_for(path)
    if backend is not None:
        removed = _run(backend.strip, backend, path) or removed
    removed = sidecar_backend.strip_sidecar(path) or removed
    return removed
