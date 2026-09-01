"""Dispatches to the right backend (native embedding where one exists,
sidecar JSON otherwise) based on file extension - the single entry point
the CLI and library callers use."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import png_backend, sidecar_backend
from .png_backend import UnreadablePngError
from .schema import Provenance, ProvenanceError

#: Extensions with a native embedding backend. Extend this (and add a new
#: `*_backend.py` module) as more native formats get support - JPEG/EXIF
#: and MP4/QuickTime atoms are the natural next candidates, deliberately
#: not implemented in v1 to keep the initial scope to one well-understood
#: format plus the universal sidecar fallback.
NATIVE_BACKEND_EXTENSIONS = {".png"}


def _has_native_backend(path: str | Path) -> bool:
    return Path(path).suffix.lower() in NATIVE_BACKEND_EXTENSIONS


def _read_png(fn, path):
    """Run a png_backend function, turning png_backend's read-phase-only
    UnreadablePngError (wrong file renamed to .png, truncated/corrupt
    download, ...) into a ProvenanceError - every CLI command already
    knows how to report a ProvenanceError cleanly. A write-phase failure
    (permission denied, disk full, ...) is a different problem and is
    deliberately left as its native exception type, not caught here."""
    try:
        return fn(path)
    except UnreadablePngError as exc:
        raise ProvenanceError(str(exc)) from exc


def embed(path: str | Path, provenance: Provenance) -> str:
    """Embed `provenance` into the asset at `path`. Returns which backend
    was used ("png" or "sidecar"), since callers/CLI output often want to
    say so explicitly rather than leave it implicit."""
    if not Path(path).exists():
        raise FileNotFoundError(f"no such file: {path}")
    if _has_native_backend(path):
        _read_png(lambda p: png_backend.embed_png(p, provenance), path)
        return "png"
    sidecar_backend.embed_sidecar(path, provenance)
    return "sidecar"


def extract(path: str | Path) -> Optional[Provenance]:
    """Look for provenance on `path`: check the native backend first (if
    one applies to this extension), then always also check for a sidecar
    file - a sidecar can legitimately exist even next to a PNG whose
    embedded chunk was stripped by some other tool along the way, and
    checking costs nothing."""
    if not Path(path).exists():
        raise FileNotFoundError(f"no such file: {path}")
    if _has_native_backend(path):
        found = _read_png(png_backend.extract_png, path)
        if found is not None:
            return found
    return sidecar_backend.extract_sidecar(path)


def strip(path: str | Path) -> bool:
    """Remove provenance from `path`, in whichever backend(s) it's present.
    Returns True if anything was actually removed."""
    if not Path(path).exists():
        raise FileNotFoundError(f"no such file: {path}")
    removed = False
    if _has_native_backend(path):
        removed = _read_png(png_backend.strip_png, path) or removed
    removed = sidecar_backend.strip_sidecar(path) or removed
    return removed
