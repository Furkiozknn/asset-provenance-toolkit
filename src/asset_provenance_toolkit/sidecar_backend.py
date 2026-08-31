"""Embed/extract provenance via a `<file>.provenance.json` sidecar.

The universal fallback: works for any file type (mp4, wav, mp3, jpg, ...)
that has no simple native text-metadata mechanism this tool implements.
The tradeoff versus the PNG backend is explicit and worth stating: a
sidecar can be separated from its asset (copied one without the other,
renamed independently) in a way an embedded chunk cannot. Prefer the
native backend wherever one exists (currently: PNG only); this is what's
left over for everything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .schema import Provenance


def sidecar_path(path: str | Path) -> Path:
    return Path(str(path) + ".provenance.json")


def embed_sidecar(path: str | Path, provenance: Provenance) -> None:
    sidecar_path(path).write_text(provenance.to_json(pretty=True), encoding="utf-8")


def extract_sidecar(path: str | Path) -> Optional[Provenance]:
    sidecar = sidecar_path(path)
    if not sidecar.exists():
        return None
    return Provenance.from_json(sidecar.read_text(encoding="utf-8"))


def strip_sidecar(path: str | Path) -> bool:
    sidecar = sidecar_path(path)
    if not sidecar.exists():
        return False
    sidecar.unlink()
    return True
