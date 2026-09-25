"""Failure paths that used to escape as raw tracebacks or lose data.

Each test here names a way a real file or a real network reaches the tool
in a shape the happy path never sees: a write interrupted halfway, a record
whose bytes are not UTF-8, a sidecar with the wrong JSON shape, a gateway
that is not listening. The contract is the same everywhere: the original
file survives, and the CLI answers with `error: ...` (or, for `verify
--json`, a JSON object), never a Python traceback.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import httpx
import pytest

from asset_provenance_toolkit import Provenance, ProvenanceError, embed, extract, strip
from asset_provenance_toolkit.cli import main
from asset_provenance_toolkit.gateway_client import JobFetchError, fetch_job_record
from asset_provenance_toolkit.jpeg_backend import _IDENTIFIER
from asset_provenance_toolkit.mp4_backend import _UUID_BYTES
from asset_provenance_toolkit.sidecar_backend import sidecar_path

from conftest import FTYP, box

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits and symlinks")


def _prov() -> Provenance:
    return Provenance(capability="c", provider="p", params={"k": 1})


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["aprov", *argv])
    main()


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF----WAVE")
    return path


@pytest.fixture(params=["sample_png", "sample_jpg", "sample_mp4", "sample_wav"])
def any_asset(request) -> Path:
    return request.getfixturevalue(request.param)


def _written_file(asset: Path) -> Path:
    """The file an embed actually rewrites: the asset itself, or its sidecar."""
    return sidecar_path(asset) if asset.suffix == ".wav" else asset


# --- atomic writes -------------------------------------------------------------


def test_failed_embed_leaves_original_intact_and_no_temp_file(any_asset: Path, monkeypatch):
    # Before: JPEG, MP4 and sidecar writes went straight through
    # Path.write_bytes, so a failure mid-write left a truncated file. Now
    # every backend writes a sibling temp file and renames it into place.
    embed(any_asset, _prov())
    target = _written_file(any_asset)
    before = target.read_bytes()
    listing = sorted(p.name for p in any_asset.parent.iterdir())

    def failing_replace(src, dst, *args, **kwargs):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        embed(any_asset, Provenance(capability="new", provider="p", params={}))

    assert target.read_bytes() == before
    assert sorted(p.name for p in any_asset.parent.iterdir()) == listing


@posix_only
@pytest.mark.parametrize("fixture", ["sample_png", "sample_jpg", "sample_mp4"])
def test_embed_and_strip_keep_the_files_permission_bits(fixture: str, request):
    asset: Path = request.getfixturevalue(fixture)
    os.chmod(asset, 0o600)

    embed(asset, _prov())
    assert stat.S_IMODE(asset.stat().st_mode) == 0o600
    assert strip(asset) is True
    assert stat.S_IMODE(asset.stat().st_mode) == 0o600


@posix_only
def test_embed_through_a_symlink_updates_the_target_and_keeps_the_link(sample_mp4: Path, tmp_path: Path):
    link = tmp_path / "latest.mp4"
    link.symlink_to(sample_mp4)

    embed(link, _prov())

    assert link.is_symlink()
    assert extract(sample_mp4) == extract(link)
    assert extract(sample_mp4) is not None


# --- corrupt records surface as ProvenanceError --------------------------------


def _jpeg_with_raw_payload(path: Path, payload: bytes) -> None:
    data = path.read_bytes()
    body = _IDENTIFIER + payload
    segment = b"\xff\xe1" + (len(body) + 2).to_bytes(2, "big") + body
    path.write_bytes(data[:2] + segment + data[2:])


def _mp4_with_raw_payload(path: Path, payload: bytes) -> None:
    uuid_box = (24 + len(payload)).to_bytes(4, "big") + b"uuid" + _UUID_BYTES + payload
    path.write_bytes(FTYP + box(b"mdat", b"media") + uuid_box)


def test_non_utf8_jpeg_record_is_a_provenance_error(sample_jpg: Path):
    _jpeg_with_raw_payload(sample_jpg, b"\xff\xfe{")
    with pytest.raises(ProvenanceError, match="UTF-8"):
        extract(sample_jpg)


def test_non_utf8_mp4_record_is_a_provenance_error(sample_mp4: Path):
    _mp4_with_raw_payload(sample_mp4, b"\xff\xfe{")
    with pytest.raises(ProvenanceError, match="UTF-8"):
        extract(sample_mp4)


def test_non_utf8_sidecar_is_a_provenance_error(sample_wav: Path):
    sidecar_path(sample_wav).write_bytes(b"\xff\xfe{")
    with pytest.raises(ProvenanceError, match="UTF-8"):
        extract(sample_wav)


@pytest.mark.parametrize(
    "field, value",
    [
        ("extra", "abc"),
        ("extra", 5),
        ("params", [1, 2]),
        ("capability", 7),
        ("provider", None),
        ("job_id", {"id": 1}),
        ("created_at", 1700000000),
    ],
)
def test_wrongly_shaped_record_is_a_provenance_error(sample_wav: Path, field, value):
    record = {"schema_version": 1, "capability": "c", "provider": "p", "params": {}}
    record[field] = value
    sidecar_path(sample_wav).write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ProvenanceError, match=field):
        extract(sample_wav)


def test_constructing_a_record_that_could_not_be_read_back_is_refused():
    with pytest.raises(ProvenanceError, match="params"):
        Provenance(capability="c", provider="p", params=["not", "an", "object"])  # type: ignore[arg-type]


def test_result_keeps_accepting_any_json_value(sample_png: Path):
    # `result` is whatever the job returned; files already written with a
    # non-object result must stay readable after this change.
    record = Provenance(capability="c", provider="p", params={}, result=["a", "b"])  # type: ignore[arg-type]
    embed(sample_png, record)
    assert extract(sample_png) == record


def test_numeric_job_id_still_roundtrips(sample_png: Path):
    record = Provenance(capability="c", provider="p", params={}, job_id=42)  # type: ignore[arg-type]
    embed(sample_png, record)
    assert extract(sample_png).job_id == 42


# --- CLI answers with error:, not a traceback -----------------------------------


def test_verify_json_on_a_corrupt_sidecar_prints_json(monkeypatch, capsys, sample_wav: Path):
    sidecar_path(sample_wav).write_bytes(b"\xff\xfe{")
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["verify", str(sample_wav), "--json"])
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "UTF-8" in out["error"]


def test_extract_on_a_directory_is_a_clean_error(monkeypatch, capsys, tmp_path: Path):
    directory = tmp_path / "looks-like.png"
    directory.mkdir()
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["extract", str(directory)])
    assert exc.value.code == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_from_job_with_a_wrongly_shaped_record_is_a_clean_error(monkeypatch, capsys, sample_png: Path):
    import asset_provenance_toolkit.cli as cli_module

    def fake_fetch(gateway_url, job_id, **kwargs):
        return {"id": job_id, "status": "ready", "capability": "c", "provider": "p", "params": "prompt=a cat"}

    monkeypatch.setattr(cli_module, "fetch_job_record", fake_fetch)
    before = sample_png.read_bytes()
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["from-job", str(sample_png), "--gateway-url", "http://gw.test", "--job-id", "j"])
    assert exc.value.code == 1
    assert "unexpected shape" in capsys.readouterr().err
    assert sample_png.read_bytes() == before


# --- gateway client -------------------------------------------------------------


def test_connection_failure_is_a_job_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused (simulated)", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(JobFetchError, match="ConnectError"):
        fetch_job_record("http://gw.test", "job-1", http_client=client)


def test_timeout_is_a_job_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out (simulated)", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(JobFetchError, match="ReadTimeout"):
        fetch_job_record("http://gw.test", "job-1", http_client=client)


def test_non_utf8_body_is_a_job_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\xff\xfe\x00{", headers={"content-type": "application/json"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(JobFetchError, match="non-JSON"):
        fetch_job_record("http://gw.test", "job-1", http_client=client)


@pytest.mark.parametrize("job_id", ["../admin", "a/b", "x?y=1", "id#frag"])
def test_job_id_is_sent_as_one_path_segment(job_id: str):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.raw_path, request.url.query))
        return httpx.Response(200, json={"status": "ready"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_job_record("http://gw.test", job_id, http_client=client)

    raw_path, query = seen[0]
    assert raw_path.startswith(b"/v1/jobs/")
    assert b"/" not in raw_path[len(b"/v1/jobs/") :]
    assert query == b""


def test_from_job_against_an_unreachable_gateway_is_a_clean_error(monkeypatch, capsys, sample_png: Path):
    import asset_provenance_toolkit.gateway_client as gw

    def refusing_get(self, url, *args, **kwargs):
        raise httpx.ConnectError("connection refused (simulated)")

    monkeypatch.setattr(gw.httpx.Client, "get", refusing_get)
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, ["from-job", str(sample_png), "--gateway-url", "http://gw.test", "--job-id", "j"])
    assert exc.value.code == 1
    assert capsys.readouterr().err.startswith("error: could not fetch job")
