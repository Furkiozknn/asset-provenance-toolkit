from __future__ import annotations

import httpx
import pytest

from asset_provenance_toolkit.gateway_client import JobFetchError, fetch_job_record


def test_fetch_job_record_returns_json_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/jobs/job-1"
        return httpx.Response(200, json={"id": "job-1", "status": "ready", "result": {"ok": True}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    record = fetch_job_record("http://gw.test", "job-1", http_client=client)
    assert record["status"] == "ready"


def test_fetch_job_record_raises_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such job")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(JobFetchError, match="404"):
        fetch_job_record("http://gw.test", "job-1", http_client=client)


def test_fetch_job_record_strips_trailing_slash_from_base_url():
    seen_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"status": "ready"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_job_record("http://gw.test/", "job-1", http_client=client)
    assert seen_paths == ["/v1/jobs/job-1"]
