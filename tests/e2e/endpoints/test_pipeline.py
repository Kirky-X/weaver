# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for pipeline endpoints (trigger, task status, queue, URL, SSE).

Contract (src/api/endpoints/content/pipeline.py):
- POST /trigger returns 200 with {task_id, status:"queued", queued_at};
  empty source_ids → 400; unknown source → 404; duplicate in-flight → 409
- GET /tasks/{id}: unknown/payload-corrupted → 404 (code 10004)
- POST /url: non-http scheme / SSRF / whitelist violations → 403
- POST /url/stream: SSE (text/event-stream); validation errors arrive as
  JSON envelope before the stream starts; concurrency cap 3 → 429
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call


@pytest.mark.e2e
class TestPipelineAuth:
    """Auth is enforced on every pipeline endpoint."""

    def test_trigger_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/trigger",
            "pipeline",
            "trigger_no_auth_expect_401",
            json_data={"source_ids": ["x"]},
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_queue_stats_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/pipeline/queue/stats",
            "pipeline",
            "queue_stats_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_url_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/url",
            "pipeline",
            "url_no_auth_expect_401",
            json_data={"url": "https://example.com/a"},
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )


@pytest.mark.e2e
class TestPipelineTrigger:
    """POST /api/v1/pipeline/trigger — async fire-and-forget."""

    def test_trigger_empty_source_ids(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/trigger",
            "pipeline",
            "trigger_empty_source_ids_expect_400",
            headers=auth_headers,
            json_data={"source_ids": []},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        assert "empty" in body["message"].lower()

    def test_trigger_unknown_sources(self, client: TestClient, recorder, auth_headers):
        ghost = f"ghost-source-{uuid.uuid4().hex[:8]}"
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/trigger",
            "pipeline",
            "trigger_unknown_source_expect_404",
            headers=auth_headers,
            json_data={"source_ids": [ghost]},
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_trigger_unknown_single_source(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/trigger",
            "pipeline",
            "trigger_unknown_single_expect_404",
            headers=auth_headers,
            json_data={"source_id": f"ghost-{uuid.uuid4().hex[:8]}"},
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_trigger_queued_response(self, client: TestClient, recorder, auth_headers):
        """No sources configured + force=true -> 200 with a queued empty task
        (the force path iterates zero sources instead of 404)."""
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/trigger",
            "pipeline",
            "trigger_force_no_sources_queued",
            headers=auth_headers,
            json_data={"force": True},
        )
        data = body["data"]
        assert set(data.keys()) >= {"task_id", "status", "queued_at"}
        assert data["status"] == "queued"
        uuid.UUID(data["task_id"])


@pytest.mark.e2e
class TestPipelineTaskStatus:
    """GET /api/v1/pipeline/tasks/{task_id}."""

    def test_task_not_found(self, client: TestClient, recorder, auth_headers):
        missing = str(uuid.uuid4())
        body = api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/pipeline/tasks/{missing}",
            "pipeline",
            "task_not_found_expect_404",
            headers=auth_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )
        assert missing in body["message"]


@pytest.mark.e2e
class TestPipelineQueue:
    """GET /api/v1/pipeline/queue/stats and /pipeline/status."""

    def test_queue_stats_payload(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/pipeline/queue/stats",
            "pipeline",
            "queue_stats",
            headers=auth_headers,
        )
        data = body["data"]
        for key in ("queue_depth", "status_counts", "total_tasks", "article_stats"):
            assert key in data, f"queue stats key {key} missing"
        stats = data["article_stats"]
        for key in (
            "total_articles",
            "processing_count",
            "completed_count",
            "failed_count",
            "pending_count",
        ):
            assert key in stats, f"article_stats.{key} missing"

    def test_pipeline_status_payload(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/pipeline/status",
            "pipeline",
            "pipeline_status",
            headers=auth_headers,
        )
        data = body["data"]
        assert data["status"] in ("running", "idle")
        assert set(data["queue"].keys()) == {"pending", "processing"}
        assert isinstance(data["recent_articles"], int)


@pytest.mark.e2e
class TestProcessUrl:
    """POST /api/v1/pipeline/url."""

    def test_url_missing(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/url",
            "pipeline",
            "url_missing_field_expect_422",
            headers=auth_headers,
            json_data={},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_url_invalid(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/url",
            "pipeline",
            "url_not_a_url_expect_422",
            headers=auth_headers,
            json_data={"url": "not-a-valid-url"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_url_local_host_blocked(self, client: TestClient, recorder, auth_headers):
        """SSRF guard: loopback targets are rejected (403), never processed."""
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/url",
            "pipeline",
            "url_loopback_expect_403",
            headers=auth_headers,
            json_data={"url": "http://127.0.0.1:8000/secret"},
            expect_status=403,
            expect_data=False,
        )
        assert body["code"] in (10001, 10003)

    def test_url_queued(self, client: TestClient, recorder, auth_headers):
        """A public URL is accepted (queued) or rejected by URL safety checks;
        both are legitimate outcomes recorded for the audit report."""
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/url",
            "pipeline",
            "url_public_queued",
            headers=auth_headers,
            json_data={"url": "https://www.example.com/article"},
        )
        data = body["data"]
        if data is not None:
            assert set(data.keys()) >= {"task_id", "status", "queued_at"}
            assert data["status"] == "queued"
            uuid.UUID(data["task_id"])  # task_id must be a valid UUID


@pytest.mark.e2e
class TestProcessUrlStream:
    """POST /api/v1/pipeline/url/stream — SSE."""

    def test_stream_invalid_url_json_error(self, client: TestClient, recorder, auth_headers):
        """Validation failures return the standard JSON envelope (pre-stream)."""
        body = api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/url/stream",
            "pipeline",
            "stream_invalid_url_expect_422",
            headers=auth_headers,
            json_data={"url": "not-a-url"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        assert "message" in body

    def test_stream_local_host_blocked(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/pipeline/url/stream",
            "pipeline",
            "stream_loopback_expect_403",
            headers=auth_headers,
            json_data={"url": "http://localhost/x"},
            expect_status=403,
            expect_data=False,
        )

    def test_stream_success_is_event_stream(self, client: TestClient, recorder, auth_headers):
        """Successful requests must switch to text/event-stream and emit events."""
        response = client.post(
            "/api/v1/pipeline/url/stream",
            headers=auth_headers,
            json={"url": "https://www.example.com/article"},
        )
        recorder.record(
            endpoint="pipeline",
            method="POST",
            url="/api/v1/pipeline/url/stream",
            request_headers=auth_headers,
            request_body={"url": "https://www.example.com/article"},
            response_status=response.status_code,
            response_headers=dict(response.headers),
            response_body=response.text[:2000],
            duration_ms=0.0,
            test_case="stream_success_content_type",
        )
        if response.status_code == 200:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert (
                "log" in response.text or "heartbeat" in response.text or "error" in response.text
            )
        else:
            # URL safety rejection — JSON envelope, documented outcome
            assert response.status_code in (403, 503)
