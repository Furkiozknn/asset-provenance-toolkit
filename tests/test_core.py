from __future__ import annotations

from pathlib import Path

import pytest

from asset_provenance_toolkit.core import embed, extract, strip
from asset_provenance_toolkit.schema import Provenance
from asset_provenance_toolkit.sidecar_backend import sidecar_path


def test_embed_on_png_uses_png_backend_not_sidecar(sample_png: Path):
    backend = embed(sample_png, Provenance(capability="c", provider="p", params={}))
    assert backend == "png"
    assert not sidecar_path(sample_png).exists()


def test_embed_on_non_png_uses_sidecar_backend(sample_non_png: Path):
    backend = embed(sample_non_png, Provenance(capability="c", provider="p", params={}))
    assert backend == "sidecar"
    assert sidecar_path(sample_non_png).exists()


def test_extract_png_reads_embedded_chunk(sample_png: Path):
    provenance = Provenance(capability="c", provider="p", params={"x": 1})
    embed(sample_png, provenance)
    assert extract(sample_png) == provenance


def test_extract_falls_back_to_sidecar_for_a_png_whose_chunk_was_stripped_elsewhere(sample_png: Path):
    # Simulate: provenance was recorded as a sidecar (e.g. by an older tool
    # version, or a workflow that couldn't re-encode the PNG), and the PNG
    # itself carries no embedded chunk at all.
    from asset_provenance_toolkit.sidecar_backend import embed_sidecar

    provenance = Provenance(capability="c", provider="p", params={})
    embed_sidecar(sample_png, provenance)
    assert extract(sample_png) == provenance


def test_extract_prefers_embedded_chunk_over_sidecar_when_both_exist(sample_png: Path):
    from asset_provenance_toolkit.sidecar_backend import embed_sidecar

    embed(sample_png, Provenance(capability="embedded", provider="p", params={}))
    embed_sidecar(sample_png, Provenance(capability="sidecar", provider="p", params={}))
    assert extract(sample_png).capability == "embedded"


def test_extract_none_when_nothing_present(sample_png: Path, sample_non_png: Path):
    assert extract(sample_png) is None
    assert extract(sample_non_png) is None


def test_strip_removes_both_png_chunk_and_any_sidecar(sample_png: Path):
    from asset_provenance_toolkit.sidecar_backend import embed_sidecar

    embed(sample_png, Provenance(capability="c", provider="p", params={}))
    embed_sidecar(sample_png, Provenance(capability="c", provider="p", params={}))

    removed = strip(sample_png)
    assert removed is True
    assert extract(sample_png) is None
    assert not sidecar_path(sample_png).exists()


def test_operations_on_missing_file_raise_file_not_found_error(tmp_path: Path):
    missing = tmp_path / "does-not-exist.png"
    with pytest.raises(FileNotFoundError):
        embed(missing, Provenance(capability="c", provider="p", params={}))
    with pytest.raises(FileNotFoundError):
        extract(missing)
    with pytest.raises(FileNotFoundError):
        strip(missing)


def test_extension_matching_is_case_insensitive(tmp_path: Path):
    from PIL import Image

    upper_png = tmp_path / "SHOUTY.PNG"
    Image.new("RGB", (4, 4)).save(upper_png)
    backend = embed(upper_png, Provenance(capability="c", provider="p", params={}))
    assert backend == "png"
