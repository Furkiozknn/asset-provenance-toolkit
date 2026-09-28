"""The Provenance record: what gets embedded in (or alongside) a generated
asset so it can be traced back to exactly what produced it.

Deliberately small and stable - this is data that has to remain readable
years after it was written, long after any job record it references has
expired out of a gateway's store. Add fields by extending `extra`, not by
silently changing what an old file already has embedded.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = 1


class ProvenanceError(Exception):
    """Raised for a malformed or unreadable provenance record."""


_JSON_NAMES = {str: "a string", int: "an integer", dict: "an object"}

#: (field, accepted types, may be None). `result` is deliberately absent:
#: it is whatever the producing job returned, and files already written
#: with a non-object result must stay readable. `job_id` accepts an int
#: because some job stores use numeric ids.
_FIELD_TYPES: tuple[tuple[str, tuple[type, ...], bool], ...] = (
    ("capability", (str,), False),
    ("provider", (str,), False),
    ("params", (dict,), False),
    ("schema_version", (int,), False),
    ("job_id", (str, int), True),
    ("source", (str,), False),
    ("source_url", (str,), True),
    ("created_at", (str,), True),
    ("extra", (dict,), False),
)


@dataclass
class Provenance:
    capability: str
    provider: str
    params: dict[str, Any]
    schema_version: int = SCHEMA_VERSION
    job_id: Optional[str] = None
    source: str = "manual"
    source_url: Optional[str] = None
    created_at: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc).isoformat()
        self._check_types()

    def _check_types(self) -> None:
        """Refuse a record whose field types this tool could not read back.

        Checked on construction, so the same rule guards both directions: a
        library caller (or a gateway returning an unexpected shape) cannot
        embed a record that `extract` would later choke on, and a record read
        from a file with the wrong shape is a ProvenanceError, not a
        TypeError from somewhere deeper."""
        for name, kinds, optional in _FIELD_TYPES:
            value = getattr(self, name)
            if value is None and optional:
                continue
            if not isinstance(value, kinds) or isinstance(value, bool):
                expected = " or ".join(_JSON_NAMES[k] for k in kinds) + (" or null" if optional else "")
                raise ProvenanceError(
                    f"provenance field {name!r} must be {expected}, got {type(value).__name__}"
                )

    def to_json(self, *, pretty: bool = False) -> str:
        data = asdict(self)
        if pretty:
            return json.dumps(data, indent=2, sort_keys=True)
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, text: str | bytes) -> "Provenance":
        """Parse a record read back from a file. `text` may be the raw bytes
        of the stored payload; bytes that are not UTF-8 are reported as a
        ProvenanceError like any other malformed record, never as a bare
        UnicodeDecodeError."""
        if isinstance(text, (bytes, bytearray)):
            try:
                text = bytes(text).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProvenanceError(f"provenance data is not valid UTF-8: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProvenanceError(f"provenance data is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ProvenanceError("provenance data must be a JSON object")

        version = data.get("schema_version")
        if version is None:
            raise ProvenanceError("provenance data is missing 'schema_version'")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ProvenanceError(f"provenance data has a non-integer 'schema_version': {version!r}")
        if version > SCHEMA_VERSION:
            raise ProvenanceError(
                f"provenance data is schema_version={version}, newer than this tool understands "
                f"(max known: {SCHEMA_VERSION}) - upgrade asset-provenance-toolkit"
            )

        missing = [k for k in ("capability", "provider", "params") if k not in data]
        if missing:
            raise ProvenanceError(f"provenance data missing required field(s): {', '.join(missing)}")

        known_fields = {f for f in cls.__dataclass_fields__}
        extra = data.get("extra") or {}
        if not isinstance(extra, dict):
            raise ProvenanceError(f"provenance field 'extra' must be an object, got {type(extra).__name__}")
        extra = dict(extra)
        kwargs = {k: v for k, v in data.items() if k in known_fields and k != "extra"}
        return cls(extra=extra, **kwargs)
