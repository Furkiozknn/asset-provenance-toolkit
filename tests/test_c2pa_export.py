"""`aprov c2pa-manifest`: a record turned into a signable C2PA manifest definition."""

from __future__ import annotations

import datetime
import json

import pytest

from asset_provenance_toolkit import Provenance, embed, extract
from asset_provenance_toolkit.c2pa_export import (
    DIGITAL_SOURCE_TYPES,
    RECIPE_ASSERTION_LABEL,
    manifest_definition,
)
from asset_provenance_toolkit.cli import main

TRAINED = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


def _record() -> Provenance:
    return Provenance(
        capability="image-generate",
        provider="flux-2",
        params={"prompt": "a red sneaker", "seed": 42},
        job_id="job-abc",
        created_at="2026-10-15T10:00:00+00:00",
    )


def _assertion(definition: dict, label: str) -> dict:
    return next(a for a in definition["assertions"] if a["label"] == label)


def test_manifest_marks_the_file_as_ai_generated_and_carries_the_recipe():
    definition = manifest_definition(_record(), title="cover.png", generator_version="0.1.0")
    (action,) = _assertion(definition, "c2pa.actions.v2")["data"]["actions"]
    assert action == {
        "action": "c2pa.created",
        "softwareAgent": "flux-2",
        "digitalSourceType": TRAINED,
        "when": "2026-10-15T10:00:00+00:00",
    }
    recipe = _assertion(definition, RECIPE_ASSERTION_LABEL)["data"]
    assert recipe == _record().to_dict()
    assert definition["title"] == "cover.png"
    assert definition["claim_generator_info"] == [
        {"name": "aprov (asset-provenance-toolkit)", "version": "0.1.0"}
    ]
    # Nothing to sign with unless asked: no key material appears by default.
    assert not {"alg", "sign_cert", "private_key", "ta_url"} & definition.keys()
    json.dumps(definition)  # JSON-serialisable as-is


@pytest.mark.parametrize("short, uri", sorted(DIGITAL_SOURCE_TYPES.items()))
def test_short_digital_source_type_names_map_to_iptc_uris(short, uri):
    definition = manifest_definition(_record(), digital_source_type=short)
    (action,) = _assertion(definition, "c2pa.actions.v2")["data"]["actions"]
    assert action["digitalSourceType"] == uri


def test_a_full_iptc_uri_is_accepted_and_anything_else_is_refused():
    uri = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
    assert manifest_definition(_record(), digital_source_type=uri)
    with pytest.raises(ValueError, match="digital source type"):
        manifest_definition(_record(), digital_source_type="ai-ish")


def test_signing_keys_are_copied_to_the_top_level_for_c2patool():
    definition = manifest_definition(
        _record(),
        signing={"alg": "es256", "sign_cert": "certs.pem", "private_key": "key.pem", "ta_url": None},
    )
    assert definition["alg"] == "es256"
    assert definition["sign_cert"] == "certs.pem"
    assert definition["private_key"] == "key.pem"
    assert "ta_url" not in definition


def _cli(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["aprov", *argv])
    main()


def test_cli_prints_the_definition_for_an_annotated_file(sample_png, monkeypatch, capsys):
    embed(sample_png, _record())
    _cli(monkeypatch, ["c2pa-manifest", str(sample_png), "--digital-source-type", "composite"])
    definition = json.loads(capsys.readouterr().out)
    assert definition["title"] == sample_png.name
    (action,) = _assertion(definition, "c2pa.actions.v2")["data"]["actions"]
    assert action["digitalSourceType"].endswith("/compositeWithTrainedAlgorithmicMedia")
    assert _assertion(definition, RECIPE_ASSERTION_LABEL)["data"]["job_id"] == "job-abc"


def test_cli_writes_to_a_file_with_signing_options(sample_jpg, tmp_path, monkeypatch, capsys):
    embed(sample_jpg, _record())
    target = tmp_path / "manifest.json"
    _cli(
        monkeypatch,
        ["c2pa-manifest", str(sample_jpg), "-o", str(target), "--alg", "es256",
         "--sign-cert", "certs.pem", "--private-key", "key.pem", "--title", "Cover"],
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wrote C2PA manifest definition" in captured.err
    definition = json.loads(target.read_text(encoding="utf-8"))
    assert definition["alg"] == "es256" and definition["title"] == "Cover"


def test_cli_refuses_a_file_without_a_record(sample_png, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, ["c2pa-manifest", str(sample_png)])
    assert exc_info.value.code == 1
    assert "no provenance found" in capsys.readouterr().err


def test_cli_refuses_an_unknown_digital_source_type(sample_png, monkeypatch, capsys):
    embed(sample_png, _record())
    with pytest.raises(SystemExit) as exc_info:
        _cli(monkeypatch, ["c2pa-manifest", str(sample_png), "--digital-source-type", "ai"])
    assert exc_info.value.code == 1
    assert "digital source type" in capsys.readouterr().err


# --- optional: really sign it -------------------------------------------------
#
# Runs only where c2pa-python and cryptography are installed (they are not
# dependencies of this project). It signs the exported definition with a
# throwaway test CA, reads the Content Credential back and checks that both
# assertions survived, and that the aprov record is still readable.


def _test_chain():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    usage = dict(content_commitment=False, key_encipherment=False, data_encipherment=False,
                 key_agreement=False, encipher_only=False, decipher_only=False)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aprov test CA"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "aprov test")])
    ca = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, **usage),
                       critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aprov test signer"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "aprov test")])
    leaf = (
        x509.CertificateBuilder().subject_name(name).issuer_name(ca_name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False, **usage),
                       critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    chain = leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return chain, key_pem


def test_the_definition_signs_with_c2pa_python_and_reads_back(sample_png, tmp_path):
    c2pa = pytest.importorskip("c2pa")
    pytest.importorskip("cryptography")
    embed(sample_png, _record())
    definition = manifest_definition(extract(sample_png), title="sample.png")
    chain, key = _test_chain()
    signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(b"es256", chain, key, None))
    signed = tmp_path / "signed.png"
    with open(sample_png, "rb") as src, open(signed, "wb") as dst:
        c2pa.Builder(json.dumps(definition)).sign(signer, "image/png", src, dst)

    with open(signed, "rb") as fh:
        store = json.loads(c2pa.Reader("image/png", fh).json())
    active = store["manifests"][store["active_manifest"]]
    labels = {a["label"] for a in active["assertions"]}
    assert {"c2pa.actions.v2", RECIPE_ASSERTION_LABEL} <= labels
    actions = next(a for a in active["assertions"] if a["label"] == "c2pa.actions.v2")
    assert actions["data"]["actions"][0]["digitalSourceType"] == TRAINED
    # The test CA is not on any trust list, so the only finding is "untrusted";
    # the signature and hard binding themselves validate.
    codes = {s["code"] for s in store.get("validation_status") or []}
    assert codes <= {"signingCredential.untrusted"}
    assert extract(signed).provider == "flux-2"
