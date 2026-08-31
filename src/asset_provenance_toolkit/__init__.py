"""asset-provenance-toolkit: embed/extract generation provenance directly in
output files - a provider-agnostic generalization of the classic
"drag the PNG back in to see its generation parameters" pattern.

Public surface::

    from asset_provenance_toolkit import (
        Provenance, ProvenanceError,
        embed, extract, strip,
        fetch_job_record, JobFetchError,
    )
"""

from __future__ import annotations

from .core import embed, extract, strip
from .gateway_client import JobFetchError, fetch_job_record
from .schema import Provenance, ProvenanceError

__all__ = [
    "Provenance",
    "ProvenanceError",
    "embed",
    "extract",
    "strip",
    "fetch_job_record",
    "JobFetchError",
]

__version__ = "0.1.0"
