from __future__ import annotations

import json

import pytest

from asset_provenance_toolkit.schema import SCHEMA_VERSION, Provenance, ProvenanceError


def test_roundtrip_via_json():
    original = Provenance(capability="mock-generate", provider="mock", params={"prompt": "a cat"})
    restored = Provenance.from_json(original.to_json())
    assert restored == original


def test_created_at_defaults_when_not_given():
    p = Provenance(capability="c", provider="p", params={})
    assert p.created_at is not None
    assert "T" in p.created_at  # ISO format


def test_created_at_preserved_when_given():
    p = Provenance(capability="c", provider="p", params={}, created_at="2026-01-01T00:00:00+00:00")
    assert p.created_at == "2026-01-01T00:00:00+00:00"


def test_extra_field_roundtrips():
    p = Provenance(capability="c", provider="p", params={}, extra={"note": "custom field"})
    restored = Provenance.from_json(p.to_json())
    assert restored.extra == {"note": "custom field"}


def test_from_json_rejects_invalid_json():
    with pytest.raises(ProvenanceError, match="not valid JSON"):
        Provenance.from_json("{not valid json")


def test_from_json_rejects_non_object():
    with pytest.raises(ProvenanceError, match="must be a JSON object"):
        Provenance.from_json(json.dumps([1, 2, 3]))


def test_from_json_rejects_missing_schema_version():
    data = {"capability": "c", "provider": "p", "params": {}}
    with pytest.raises(ProvenanceError, match="missing 'schema_version'"):
        Provenance.from_json(json.dumps(data))


def test_from_json_rejects_missing_required_fields():
    data = {"schema_version": SCHEMA_VERSION, "capability": "c"}
    with pytest.raises(ProvenanceError, match="missing required field"):
        Provenance.from_json(json.dumps(data))


def test_from_json_rejects_future_schema_version():
    data = {
        "schema_version": SCHEMA_VERSION + 1,
        "capability": "c",
        "provider": "p",
        "params": {},
    }
    with pytest.raises(ProvenanceError, match="newer than this tool understands"):
        Provenance.from_json(json.dumps(data))


def test_pretty_json_is_multiline_and_compact_is_single_line():
    p = Provenance(capability="c", provider="p", params={"a": 1})
    assert "\n" in p.to_json(pretty=True)
    assert "\n" not in p.to_json(pretty=False)


def test_to_dict_matches_json_roundtrip():
    p = Provenance(capability="c", provider="p", params={"a": 1})
    assert json.loads(p.to_json()) == p.to_dict()
