# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for saga endpoints.

Contract highlights (src/api/endpoints/saga.py):
- GET /saga/{saga_id}, POST compensate, POST retry, GET article/{id} return
  BARE dicts (no APIResponse envelope) — only /saga/failed/list is enveloped
- Non-UUID saga_id / article_id → 422
- Unknown saga → 404 for status/compensate/retry
- compensate has no state check: a saga with no completed steps yields 500
  "Compensation failed"; retry merely identifies the article (200) even for
  non-failed sagas, but 404 when no log entries exist
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call


@pytest.mark.e2e
class TestSagaAuth:
    """Status/article/failed-list use regular auth; compensate/retry admin."""

    def test_status_requires_auth(self, client: TestClient, recorder):
        saga_id = str(uuid.uuid4())
        api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/saga/{saga_id}",
            "saga",
            "saga_status_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_compensate_requires_admin(self, client: TestClient, recorder, auth_headers):
        saga_id = str(uuid.uuid4())
        api_call(
            client,
            recorder,
            "POST",
            f"/api/v1/saga/{saga_id}/compensate",
            "saga",
            "saga_compensate_regular_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )

    def test_retry_requires_admin(self, client: TestClient, recorder, auth_headers):
        saga_id = str(uuid.uuid4())
        api_call(
            client,
            recorder,
            "POST",
            f"/api/v1/saga/{saga_id}/retry",
            "saga",
            "saga_retry_regular_expect_403",
            headers=auth_headers,
            expect_status=403,
            expect_code=10003,
            expect_data=False,
        )


@pytest.mark.e2e
class TestSagaValidation:
    """Path parameter format validation."""

    def test_status_invalid_uuid(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/saga/not-a-uuid",
            "saga",
            "saga_status_invalid_uuid_expect_422",
            headers=auth_headers,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_article_invalid_uuid(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/saga/article/not-a-uuid",
            "saga",
            "saga_article_invalid_uuid_expect_422",
            headers=auth_headers,
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestSagaUnknownResources:
    """Unknown saga/article lookups on an empty saga log."""

    def test_status_unknown_saga(self, client: TestClient, recorder, auth_headers):
        saga_id = str(uuid.uuid4())
        body = api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/saga/{saga_id}",
            "saga",
            "saga_status_unknown_expect_404",
            headers=auth_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )
        assert saga_id in body["message"]

    def test_compensate_unknown_saga(self, client: TestClient, recorder, admin_headers):
        saga_id = str(uuid.uuid4())
        api_call(
            client,
            recorder,
            "POST",
            f"/api/v1/saga/{saga_id}/compensate",
            "saga",
            "saga_compensate_unknown_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_retry_unknown_saga(self, client: TestClient, recorder, admin_headers):
        saga_id = str(uuid.uuid4())
        api_call(
            client,
            recorder,
            "POST",
            f"/api/v1/saga/{saga_id}/retry",
            "saga",
            "saga_retry_unknown_expect_404",
            headers=admin_headers,
            expect_status=404,
            expect_code=10004,
            expect_data=False,
        )

    def test_article_sagas_empty(self, client: TestClient, recorder, auth_headers):
        """Unknown article → 200 with empty saga_logs (bare dict, no envelope)."""
        article_id = str(uuid.uuid4())
        body = api_call(
            client,
            recorder,
            "GET",
            f"/api/v1/saga/article/{article_id}",
            "saga",
            "saga_article_empty",
            headers=auth_headers,
            expect_envelope=False,
        )
        assert body["article_id"] == article_id
        assert body["saga_logs"] == []

    def test_failed_list_enveloped(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/saga/failed/list",
            "saga",
            "saga_failed_list",
            headers=auth_headers,
        )
        data = body["data"]
        assert "failed_count" in data
        assert isinstance(data["entries"], list)
        for entry in data["entries"]:
            for key in ("id", "saga_id", "article_id", "step_name", "step_status"):
                assert key in entry, f"failed entry key {key} missing"

    def test_failed_list_limit_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/saga/failed/list",
            "saga",
            "saga_failed_list_limit_201_expect_422",
            headers=auth_headers,
            params={"limit": "201"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
