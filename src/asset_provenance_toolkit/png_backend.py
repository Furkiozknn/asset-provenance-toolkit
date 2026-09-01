"""Embed/extract provenance in a PNG's own tEXt metadata chunk.

This is the AUTOMATIC1111 "drag the image back in to see how it was made"
pattern, generalized to be provider-agnostic: the provenance JSON lives in
the pixel file itself, so the asset stays fully self-describing wherever it
travels - no database, no sidecar required for this format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, PngImagePlugin, UnidentifiedImageError

from .schema import Provenance

#: PNG tEXt keyword this tool reads/writes. Keywords are conventionally
#: short and namespaced to avoid colliding with other tools' metadata.
PROVENANCE_KEY = "ai-provenance"


class UnreadablePngError(Exception):
    """Raised only for a read-phase failure (PIL can't identify/decode the
    file as a PNG at all) - deliberately never raised for a write-phase
    failure (permission denied, disk full, ...), which is a different
    problem with a different fix and must not be mislabeled as this one."""


def _open_and_read(path: str | Path, *, copy_pixels: bool):
    """Open `path`, fully load its pixel data, and return (pixel_image or
    None, text_dict). `copy_pixels` is False for the read-only extract path,
    which never saves anything back and shouldn't pay for copying pixel data
    it will just discard.

    The only place read-phase errors are caught and reclassified - a
    write-phase OSError (e.g. saving back to a read-only file) happens
    later, outside this function, and is deliberately left as its native
    exception type rather than being caught here too."""
    try:
        with Image.open(path) as img:
            img.load()
            pixel_image = img.copy() if copy_pixels else None
            return pixel_image, dict(getattr(img, "text", {}) or {})
    except FileNotFoundError:
        raise  # a TOCTOU race (deleted between the caller's exists() check and
        # this open) is a missing-file problem, not an unreadable-PNG one -
        # let it propagate as the FileNotFoundError every caller already handles.
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadablePngError(f"{path}: not a readable PNG file ({exc})") from exc


def embed_png(path: str | Path, provenance: Provenance) -> None:
    """Re-save the PNG with provenance written into its tEXt chunks.

    Lossless: PNG re-encoding does not touch pixel data. Any other text
    chunks already present (e.g. from a different tool) are preserved,
    except a stale copy of this tool's own key, which is replaced.
    """
    pixel_image, existing = _open_and_read(path, copy_pixels=True)

    info = PngImagePlugin.PngInfo()
    for key, value in existing.items():
        if key != PROVENANCE_KEY:
            info.add_text(key, value)
    info.add_text(PROVENANCE_KEY, provenance.to_json())

    pixel_image.save(path, pnginfo=info)


def extract_png(path: str | Path) -> Optional[Provenance]:
    _pixel_image, existing = _open_and_read(path, copy_pixels=False)
    raw = existing.get(PROVENANCE_KEY)
    if raw is None:
        return None
    return Provenance.from_json(raw)


def strip_png(path: str | Path) -> bool:
    """Remove this tool's provenance chunk, preserving every other chunk.
    Returns False (no-op) if there was nothing to remove."""
    pixel_image, existing = _open_and_read(path, copy_pixels=True)
    if PROVENANCE_KEY not in existing:
        return False

    info = PngImagePlugin.PngInfo()
    for key, value in existing.items():
        if key != PROVENANCE_KEY:
            info.add_text(key, value)
    pixel_image.save(path, pnginfo=info)
    return True
