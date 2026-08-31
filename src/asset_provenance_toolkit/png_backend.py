"""Embed/extract provenance in a PNG's own tEXt metadata chunk.

This is the AUTOMATIC1111 "drag the image back in to see how it was made"
pattern, generalized to be provider-agnostic: the provenance JSON lives in
the pixel file itself, so the asset stays fully self-describing wherever it
travels - no database, no sidecar required for this format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, PngImagePlugin

from .schema import Provenance

#: PNG tEXt keyword this tool reads/writes. Keywords are conventionally
#: short and namespaced to avoid colliding with other tools' metadata.
PROVENANCE_KEY = "ai-provenance"


def _read_existing_text(path: str | Path) -> dict[str, str]:
    with Image.open(path) as img:
        img.load()
        return dict(getattr(img, "text", {}) or {})


def embed_png(path: str | Path, provenance: Provenance) -> None:
    """Re-save the PNG with provenance written into its tEXt chunks.

    Lossless: PNG re-encoding does not touch pixel data. Any other text
    chunks already present (e.g. from a different tool) are preserved,
    except a stale copy of this tool's own key, which is replaced.
    """
    with Image.open(path) as img:
        img.load()
        existing = dict(getattr(img, "text", {}) or {})
        pixel_image = img.copy()

    info = PngImagePlugin.PngInfo()
    for key, value in existing.items():
        if key != PROVENANCE_KEY:
            info.add_text(key, value)
    info.add_text(PROVENANCE_KEY, provenance.to_json())

    pixel_image.save(path, pnginfo=info)


def extract_png(path: str | Path) -> Optional[Provenance]:
    raw = _read_existing_text(path).get(PROVENANCE_KEY)
    if raw is None:
        return None
    return Provenance.from_json(raw)


def strip_png(path: str | Path) -> bool:
    """Remove this tool's provenance chunk, preserving every other chunk.
    Returns False (no-op) if there was nothing to remove."""
    with Image.open(path) as img:
        img.load()
        existing = dict(getattr(img, "text", {}) or {})
        if PROVENANCE_KEY not in existing:
            return False
        pixel_image = img.copy()

    info = PngImagePlugin.PngInfo()
    for key, value in existing.items():
        if key != PROVENANCE_KEY:
            info.add_text(key, value)
    pixel_image.save(path, pnginfo=info)
    return True
