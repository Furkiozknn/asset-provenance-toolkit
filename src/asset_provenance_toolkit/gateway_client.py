"""Fetch a job record from an ai-job-gateway-compatible server.

No Python dependency on the `ai-job-gateway` package - same ecosystem
policy as `prompt-template-manager` and `model-comparison-harness` --
coupling only through the documented HTTP contract.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx


class JobFetchError(Exception):
    pass


def fetch_job_record(
    gateway_url: str, job_id: str, *, http_client: Optional[httpx.Client] = None
) -> dict[str, Any]:
    client = http_client or httpx.Client()
    owns_client = http_client is None
    # The job id is a single path segment. Quoting it with no safe characters
    # means an id such as "../admin" or "x?y=1" is sent as data, not
    # reinterpreted as a different path or query on the gateway.
    url = f"{gateway_url.rstrip('/')}/v1/jobs/{quote(job_id, safe='')}"
    try:
        try:
            response = client.get(url)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # Connection refused, DNS failure, timeout, malformed URL: the
            # same "could not fetch" category as an HTTP error status, and
            # the CLI already reports JobFetchError cleanly.
            raise JobFetchError(
                f"could not fetch job {job_id!r} from {gateway_url}: {type(exc).__name__}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise JobFetchError(
                f"could not fetch job {job_id!r} from {gateway_url}: HTTP {response.status_code} - {response.text}"
            )
        try:
            record = response.json()
        except ValueError as exc:  # JSONDecodeError, or a body that is not valid text at all
            raise JobFetchError(
                f"gateway at {gateway_url} returned a non-JSON response for job {job_id!r}: {exc}"
            ) from exc
        if not isinstance(record, dict):
            raise JobFetchError(
                f"gateway at {gateway_url} returned a JSON {type(record).__name__} for job {job_id!r}, expected an object"
            )
        return record
    finally:
        if owns_client:
            client.close()
