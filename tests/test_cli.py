from __future__ import annotations

import json
from pathlib import Path

import pytest

from asset_provenance_toolkit.cli import main


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["aprov", *argv])
    main()


def test_embed_and_extract_roundtrip(monkeypatch, capsys, sample_png: Path):
    _run(
        monkeypatch,
        [
            "embed",
            str(sample_png),
            "--capability",
            "mock-generate",
            "--provider",
            "mock",
            "--params",
            '{"prompt": "a cat"}',
        ],
    )
    out = capsys.readouterr().out
    assert "embedded provenance" in out
    assert "(png backend)" in out

    _run(monkeypatch, ["extract", str(sample_png), "--compact"])
    extracted = json.loads(capsys.readouterr().out)
    assert extracted["capability"] == "mock-generate"
    assert extracted["params"] == {"prompt": "a cat"}


def test_embed_invalid_params_json_exits_nonzero(monkeypatch, capsys, sample_png: Path):
    with pytest.raises(SystemExit) as exc_info:
        _run(
            monkeypatch,
            ["embed", str(sample_png), "--capability", "c", "--provider", "p", "--params", "not json"],
        )
    assert exc_info.value.code == 1
    assert "must be valid JSON" in capsys.readouterr().err


def test_extract_missing_provenance_exits_nonzero(monkeypatch, capsys, sample_png: Path):
    with pytest.raises(SystemExit) as exc_info:
        _run(monkeypatch, ["extract", str(sample_png)])
    assert exc_info.value.code == 1
    assert "no provenance found" in capsys.readouterr().err


def test_verify_ok(monkeypatch, capsys, sample_png: Path):
    _run(monkeypatch, ["embed", str(sample_png), "--capability", "c", "--provider", "p"])
    capsys.readouterr()
    _run(monkeypatch, ["verify", str(sample_png)])
    assert "OK:" in capsys.readouterr().out


def test_verify_fail(monkeypatch, capsys, sample_png: Path):
    with pytest.raises(SystemExit) as exc_info:
        _run(monkeypatch, ["verify", str(sample_png)])
    assert exc_info.value.code == 1
    assert "FAIL:" in capsys.readouterr().out


def test_verify_json_ok(monkeypatch, capsys, sample_png: Path):
    _run(monkeypatch, ["embed", str(sample_png), "--capability", "c", "--provider", "p"])
    capsys.readouterr()
    _run(monkeypatch, ["verify", str(sample_png), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["provenance"]["capability"] == "c"


def test_verify_json_fail(monkeypatch, capsys, sample_png: Path):
    with pytest.raises(SystemExit) as exc_info:
        _run(monkeypatch, ["verify", str(sample_png), "--json"])
    assert exc_info.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_embed_on_jpeg_uses_jpeg_backend(monkeypatch, capsys, sample_jpg: Path):
    _run(
        monkeypatch,
        ["embed", str(sample_jpg), "--capability", "c", "--provider", "p"],
    )
    out = capsys.readouterr().out
    assert "(jpeg backend)" in out

    _run(monkeypatch, ["extract", str(sample_jpg), "--compact"])
    extracted = json.loads(capsys.readouterr().out)
    assert extracted["capability"] == "c"


def test_embed_with_extra_fields_roundtrips(monkeypatch, capsys, sample_png: Path):
    _run(
        monkeypatch,
        [
            "embed",
            str(sample_png),
            "--capability",
            "c",
            "--provider",
            "p",
            "--extra",
            '{"seed": 42}',
        ],
    )
    capsys.readouterr()
    _run(monkeypatch, ["extract", str(sample_png), "--compact"])
    extracted = json.loads(capsys.readouterr().out)
    assert extracted["extra"] == {"seed": 42}


def test_embed_invalid_extra_json_exits_nonzero(monkeypatch, capsys, sample_png: Path):
    with pytest.raises(SystemExit) as exc_info:
        _run(
            monkeypatch,
            ["embed", str(sample_png), "--capability", "c", "--provider", "p", "--extra", "not json"],
        )
    assert exc_info.value.code == 1
    assert "must be valid JSON" in capsys.readouterr().err


def test_strip(monkeypatch, capsys, sample_png: Path):
    _run(monkeypatch, ["embed", str(sample_png), "--capability", "c", "--provider", "p"])
    capsys.readouterr()
    _run(monkeypatch, ["strip", str(sample_png)])
    assert "removed provenance" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        _run(monkeypatch, ["extract", str(sample_png)])


def test_strip_nothing_to_remove(monkeypatch, capsys, sample_png: Path):
    _run(monkeypatch, ["strip", str(sample_png)])
    assert "nothing to remove" in capsys.readouterr().out


def test_from_job_happy_path(monkeypatch, capsys, sample_png: Path):
    import asset_provenance_toolkit.cli as cli_module

    def fake_fetch(gateway_url, job_id, **kwargs):
        return {
            "id": job_id,
            "status": "ready",
            "capability": "mock-generate",
            "provider": "mock",
            "params": {"prompt": "a cat"},
            "created_at": "2026-01-01T00:00:00+00:00",
            "result": {"output": "..."},
        }

    monkeypatch.setattr(cli_module, "fetch_job_record", fake_fetch)

    _run(
        monkeypatch,
        ["from-job", str(sample_png), "--gateway-url", "http://gw.test", "--job-id", "job-1"],
    )
    out = capsys.readouterr().out
    assert "embedded provenance from job job-1" in out

    _run(monkeypatch, ["extract", str(sample_png), "--compact"])
    extracted = json.loads(capsys.readouterr().out)
    assert extracted["source"] == "ai-job-gateway"
    assert extracted["job_id"] == "job-1"
    assert extracted["params"] == {"prompt": "a cat"}


def test_from_job_not_ready_exits_nonzero(monkeypatch, capsys, sample_png: Path):
    import asset_provenance_toolkit.cli as cli_module

    monkeypatch.setattr(
        cli_module, "fetch_job_record", lambda gateway_url, job_id, **kwargs: {"status": "processing"}
    )

    with pytest.raises(SystemExit) as exc_info:
        _run(
            monkeypatch,
            ["from-job", str(sample_png), "--gateway-url", "http://gw.test", "--job-id", "job-1"],
        )
    assert exc_info.value.code == 1
    assert "not ready" in capsys.readouterr().err


def test_from_job_on_corrupt_png_exits_cleanly_not_a_raw_traceback(monkeypatch, capsys, tmp_path: Path):
    import asset_provenance_toolkit.cli as cli_module

    fake_png = tmp_path / "corrupt.png"
    fake_png.write_bytes(b"not really a png")

    monkeypatch.setattr(
        cli_module,
        "fetch_job_record",
        lambda gateway_url, job_id, **kwargs: {
            "id": job_id,
            "status": "ready",
            "capability": "c",
            "provider": "p",
            "params": {},
        },
    )

    with pytest.raises(SystemExit) as exc_info:
        _run(
            monkeypatch,
            ["from-job", str(fake_png), "--gateway-url", "http://gw.test", "--job-id", "job-1"],
        )
    assert exc_info.value.code == 1
    assert "not a readable PNG" in capsys.readouterr().err


def test_from_job_fetch_error_exits_nonzero(monkeypatch, capsys, sample_png: Path):
    import asset_provenance_toolkit.cli as cli_module
    from asset_provenance_toolkit.gateway_client import JobFetchError

    def raise_error(gateway_url, job_id, **kwargs):
        raise JobFetchError("boom")

    monkeypatch.setattr(cli_module, "fetch_job_record", raise_error)

    with pytest.raises(SystemExit) as exc_info:
        _run(
            monkeypatch,
            ["from-job", str(sample_png), "--gateway-url", "http://gw.test", "--job-id", "job-1"],
        )
    assert exc_info.value.code == 1
    assert "boom" in capsys.readouterr().err
