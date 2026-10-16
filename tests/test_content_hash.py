"""content_hash: record what the file looked like, then tell whether it changed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from asset_provenance_toolkit import (
    Provenance,
    ProvenanceError,
    check_content,
    content_digest,
    embed,
    extract,
    strip,
)
from asset_provenance_toolkit.cli import main

FIXTURES = ["sample_png", "sample_jpg", "sample_mp4", "sample_mp4_faststart", "sample_non_png"]


def _record(**kw) -> Provenance:
    return Provenance(capability="image-generate", provider="flux-2", params={"seed": 1}, **kw)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_digest_is_the_same_before_embed_after_embed_and_after_strip(fixture, request):
    path: Path = request.getfixturevalue(fixture)
    before = content_digest(path)
    embed(path, _record(), bind_content=True)
    after = content_digest(path)
    strip(path)
    stripped = content_digest(path)
    assert before == after == stripped
    assert before.startswith("sha256:") and len(before) == len("sha256:") + 64


@pytest.mark.parametrize("fixture", FIXTURES)
def test_bound_record_matches_until_the_content_changes(fixture, request):
    path: Path = request.getfixturevalue(fixture)
    embed(path, _record(), bind_content=True)
    found = extract(path)
    assert found.content_hash == content_digest(path)
    assert check_content(path, found).status == "match"

    # Change one byte of real content: the image data, the media data, or
    # the sidecar-backed file itself. Re-embedding is what moves the record.
    raw = bytearray(path.read_bytes())
    if fixture == "sample_png":
        # Rewrite the pixels through Pillow, keeping our chunk, as an editor would.
        found_text = extract(path).to_json()
        Image.new("RGB", (16, 16), (1, 2, 3)).save(path)
        embed(path, Provenance.from_json(found_text))  # old hash, new pixels
    elif fixture == "sample_non_png":
        path.write_bytes(bytes(raw) + b"tampered")
    else:
        # Flip one byte of the payload: JPEG scan data just before EOI, or
        # the first media chunk inside mdat.
        index = len(raw) - 10 if fixture == "sample_jpg" else raw.index(b"CHUNK-ONE") + 3
        raw[index] ^= 0xFF
        path.write_bytes(bytes(raw))
    check = check_content(path, extract(path))
    assert check.status == "mismatch"
    assert check.expected == found.content_hash
    assert check.actual != check.expected


def test_sidecar_digest_is_the_plain_file_sha256(sample_non_png):
    expected = "sha256:" + hashlib.sha256(sample_non_png.read_bytes()).hexdigest()
    assert content_digest(sample_non_png) == expected


def test_reembedding_keeps_the_hash_stable(sample_png):
    embed(sample_png, _record(), bind_content=True)
    first = extract(sample_png).content_hash
    embed(sample_png, _record(job_id="second"), bind_content=True)
    assert extract(sample_png).content_hash == first


def test_library_default_does_not_bind_and_does_not_mutate_the_callers_record(sample_png):
    record = _record()
    embed(sample_png, record)
    assert extract(sample_png).content_hash is None
    embed(sample_png, record, bind_content=True)
    assert record.content_hash is None
    assert extract(sample_png).content_hash is not None


def test_unbound_and_unsupported_records(sample_png):
    assert check_content(sample_png, _record()).status == "unbound"
    assert check_content(sample_png, _record(content_hash="md5:abc")).status == "unsupported"


def test_content_hash_must_be_a_string():
    with pytest.raises(ProvenanceError, match="content_hash"):
        _record(content_hash=123)


def test_an_older_record_without_the_field_still_reads():
    old = {"schema_version": 1, "capability": "c", "provider": "p", "params": {}}
    assert Provenance.from_json(json.dumps(old)).content_hash is None


# --- CLI ---------------------------------------------------------------------


def _cli(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["aprov", *argv])
    main()


def test_cli_embed_records_a_hash_and_verify_checks_it(sample_jpg, monkeypatch, capsys):
    _cli(monkeypatch, ["embed", str(sample_jpg), "--capability", "c", "--provider", "p"])
    capsys.readouterr()
    assert extract(sample_jpg).content_hash == content_digest(sample_jpg)

    _cli(monkeypatch, ["verify", str(sample_jpg)])
    assert "content unchanged since the record was written" in capsys.readouterr().out

    raw = bytearray(sample_jpg.read_bytes())
    raw[-10] ^= 0xFF  # inside the scan data, before EOI
    sample_jpg.write_bytes(bytes(raw))
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, ["verify", str(sample_jpg)])
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL:") and "content CHANGED" in out

    with pytest.raises(SystemExit):
        _cli(monkeypatch, ["verify", str(sample_jpg), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["content"]["status"] == "mismatch"


def test_cli_no_content_hash_and_require_content_hash(sample_png, monkeypatch, capsys):
    _cli(monkeypatch, ["embed", str(sample_png), "--capability", "c", "--provider", "p", "--no-content-hash"])
    capsys.readouterr()
    assert extract(sample_png).content_hash is None

    _cli(monkeypatch, ["verify", str(sample_png)])  # still OK: nothing to compare
    assert "no content hash recorded" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, ["verify", str(sample_png), "--require-content-hash"])
    assert exc_info.value.code == 1
    assert "no content hash recorded" in capsys.readouterr().out

    _cli(monkeypatch, ["verify", str(sample_png), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["content"]["status"] == "unbound"


def test_cli_verify_catches_a_different_file_swapped_in_next_to_a_sidecar(sample_non_png, monkeypatch, capsys):
    _cli(monkeypatch, ["embed", str(sample_non_png), "--capability", "c", "--provider", "p"])
    capsys.readouterr()
    sample_non_png.write_bytes(b"RIFF\x24\x00\x00\x00WAVE a different recording")
    with pytest.raises(SystemExit):
        _cli(monkeypatch, ["verify", str(sample_non_png)])
    assert "content CHANGED" in capsys.readouterr().out
