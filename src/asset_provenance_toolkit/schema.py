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

    def to_json(self, *, pretty: bool = False) -> str:
        data = asdict(self)
        if pretty:
            return json.dumps(data, indent=2, sort_keys=True)
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, text: str) -> "Provenance":
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
        extra = dict(data.get("extra") or {})
        kwargs = {k: v for k, v in data.items() if k in known_fields and k != "extra"}
        return cls(extra=extra, **kwargs)
