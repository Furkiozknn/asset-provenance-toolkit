from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    path = tmp_path / "sample.png"
    Image.new("RGB", (16, 16), (200, 100, 50)).save(path)
    return path


@pytest.fixture
def sample_jpg(tmp_path: Path) -> Path:
    path = tmp_path / "sample.jpg"
    Image.new("RGB", (16, 16), (50, 100, 200)).save(path, format="JPEG", quality=90)
    return path


@pytest.fixture
def sample_non_png(tmp_path: Path) -> Path:
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"not a real mp4, just bytes for the sidecar backend to sit next to")
    return path
