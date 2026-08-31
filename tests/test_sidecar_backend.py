from __future__ import annotations

from pathlib import Path

from asset_provenance_toolkit.schema import Provenance
from asset_provenance_toolkit.sidecar_backend import embed_sidecar, extract_sidecar, sidecar_path, strip_sidecar


def test_sidecar_path_appends_suffix(tmp_path: Path):
    target = tmp_path / "clip.mp4"
    assert sidecar_path(target) == Path(str(target) + ".provenance.json")


def test_extract_returns_none_when_no_sidecar_exists(sample_non_png: Path):
    assert extract_sidecar(sample_non_png) is None


def test_embed_creates_sidecar_file_next_to_asset(sample_non_png: Path):
    embed_sidecar(sample_non_png, Provenance(capability="c", provider="p", params={}))
    assert sidecar_path(sample_non_png).exists()


def test_embed_then_extract_roundtrips(sample_non_png: Path):
    provenance = Provenance(capability="video-gen", provider="mock", params={"prompt": "a cat, video"})
    embed_sidecar(sample_non_png, provenance)
    assert extract_sidecar(sample_non_png) == provenance


def test_embed_does_not_touch_the_original_asset_bytes(sample_non_png: Path):
    original_bytes = sample_non_png.read_bytes()
    embed_sidecar(sample_non_png, Provenance(capability="c", provider="p", params={}))
    assert sample_non_png.read_bytes() == original_bytes


def test_strip_removes_sidecar_and_reports_true(sample_non_png: Path):
    embed_sidecar(sample_non_png, Provenance(capability="c", provider="p", params={}))
    assert strip_sidecar(sample_non_png) is True
    assert not sidecar_path(sample_non_png).exists()


def test_strip_with_no_sidecar_is_a_noop_reporting_false(sample_non_png: Path):
    assert strip_sidecar(sample_non_png) is False
