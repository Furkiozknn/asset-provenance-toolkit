"""Fetch a job record from an ai-job-gateway-compatible server.

No Python dependency on the `ai-job-gateway` package - same ecosystem
policy as `prompt-template-manager` and `model-comparison-harness`
(see ADR-006 in the lab's DECISIONS.md): coupling only through the
documented HTTP contract.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx


class JobFetchError(Exception):
    pass


def fetch_job_record(
    gateway_url: str, job_id: str, *, http_client: Optional[httpx.Client] = None
) -> dict[str, Any]:
    client = http_client or httpx.Client()
    owns_client = http_client is None
    try:
        response = client.get(f"{gateway_url.rstrip('/')}/v1/jobs/{job_id}")
        if response.status_code >= 400:
            raise JobFetchError(
                f"could not fetch job {job_id!r} from {gateway_url}: HTTP {response.status_code} - {response.text}"
            )
        return response.json()
    finally:
        if owns_client:
            client.close()
