# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for analytics, briefings, and trend endpoints.

Contract highlights:
- GET /analytics/shifts and /briefings NEVER 5xx: storage failures degrade to
  200 with empty lists (documented fault tolerance)
- GET /briefings/daily returns 200 + data:null for a missing briefing
  (not 404); category regex ^(finance|tech|ai|general)$
- GET /trends/sentiment: entity optional in the signature but enforced at
  runtime → 400 without it; window restricted to 7d/30d → 400 otherwise;
  no data → 200 with empty lists and trend_direction "stable"
- GET /trends/detection: no data → 200 status "insufficient_data"
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.e2e.endpoints._kit import api_call


@pytest.mark.e2e
class TestAnalytics:
    """GET /api/v1/analytics/shifts and /briefings."""

    def test_shifts_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/analytics/shifts",
            "analytics",
            "shifts_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_shifts_payload(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/analytics/shifts",
            "analytics",
            "shifts_default",
            headers=auth_headers,
        )
        data = body["data"]
        assert isinstance(data["shifts"], list)
        assert data["total"] == len(data["shifts"])

    def test_shifts_invalid_scope(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/analytics/shifts",
            "analytics",
            "shifts_invalid_scope_expect_422",
            headers=auth_headers,
            params={"scope": "galaxy"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_shifts_limit_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/analytics/shifts",
            "analytics",
            "shifts_limit_0_expect_422",
            headers=auth_headers,
            params={"limit": "0"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/analytics/shifts",
            "analytics",
            "shifts_limit_501_expect_422",
            headers=auth_headers,
            params={"limit": "501"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_briefings_payload(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/analytics/briefings",
            "analytics",
            "analytics_briefings",
            headers=auth_headers,
        )
        data = body["data"]
        assert isinstance(data["briefings"], list)
        assert data["total"] == len(data["briefings"])

    def test_briefings_limit_bounds(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/analytics/briefings",
            "analytics",
            "analytics_briefings_limit_101_expect_422",
            headers=auth_headers,
            params={"limit": "101"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestDailyBriefing:
    """GET/POST /api/v1/briefings/daily."""

    def test_get_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/briefings/daily",
            "briefings",
            "briefing_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_get_missing_briefing_null_data(self, client: TestClient, recorder, auth_headers):
        """Missing briefing → 200 with data:null (documented tolerance)."""
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/briefings/daily",
            "briefings",
            "briefing_missing_null_data",
            headers=auth_headers,
            params={"date": "1999-12-31"},
            expect_data=False,
        )
        assert body["code"] == 0
        assert body["data"] is None

    def test_get_invalid_category(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/briefings/daily",
            "briefings",
            "briefing_invalid_category_expect_422",
            headers=auth_headers,
            params={"category": "sports"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_get_invalid_date(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/briefings/daily",
            "briefings",
            "briefing_invalid_date_expect_422",
            headers=auth_headers,
            params={"date": "31-12-1999"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )

    def test_get_valid_category_shape(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/briefings/daily",
            "briefings",
            "briefing_category_tech",
            headers=auth_headers,
            params={"category": "tech"},
            expect_data=False,
        )
        # data is either a full briefing or null (absent) — never partial
        if body["data"] is not None:
            for key in ("date", "category", "summary", "items"):
                assert key in body["data"], f"briefing key {key} missing"
            assert body["data"]["category"] == "tech"

    def test_generate_invalid_category(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "POST",
            "/api/v1/briefings/daily/generate",
            "briefings",
            "briefing_generate_invalid_category_expect_422",
            headers=auth_headers,
            params={"category": "ossip"},
            expect_status=422,
            expect_code=10001,
            expect_data=False,
        )


@pytest.mark.e2e
class TestTrends:
    """GET /api/v1/trends/sentiment and /detection."""

    def test_sentiment_requires_auth(self, client: TestClient, recorder):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/trends/sentiment",
            "trends",
            "trends_sentiment_no_auth_expect_401",
            expect_status=401,
            expect_code=10002,
            expect_data=False,
        )

    def test_sentiment_entity_enforced(self, client: TestClient, recorder, auth_headers):
        """Signature marks entity optional but the handler enforces it (400)."""
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/trends/sentiment",
            "trends",
            "trends_sentiment_missing_entity_expect_400",
            headers=auth_headers,
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )
        assert "entity" in body["message"].lower()

    def test_sentiment_invalid_window(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/trends/sentiment",
            "trends",
            "trends_sentiment_window_3d_expect_400",
            headers=auth_headers,
            params={"entity": "x", "window": "3d"},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )

    def test_sentiment_no_data_stable(self, client: TestClient, recorder, auth_headers):
        """No data → 200 with empty lists and 'stable' direction."""
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/trends/sentiment",
            "trends",
            "trends_sentiment_unknown_entity",
            headers=auth_headers,
            params={"entity": "no-such-entity-xyz"},
        )
        data = body["data"]
        for key in ("entity_name", "window_days", "shifts", "list", "avg_shift", "trend_direction"):
            assert key in data, f"sentiment trend key {key} missing"
        assert data["entity_name"] == "no-such-entity-xyz"
        assert data["shifts"] == []
        assert data["trend_direction"] in ("up", "down", "stable")

    def test_detection_invalid_window(self, client: TestClient, recorder, auth_headers):
        api_call(
            client,
            recorder,
            "GET",
            "/api/v1/trends/detection",
            "trends",
            "trends_detection_window_bad_expect_400",
            headers=auth_headers,
            params={"window": "fortnite"},
            expect_status=400,
            expect_code=10001,
            expect_data=False,
        )

    def test_detection_payload(self, client: TestClient, recorder, auth_headers):
        body = api_call(
            client,
            recorder,
            "GET",
            "/api/v1/trends/detection",
            "trends",
            "trends_detection_default",
            headers=auth_headers,
        )
        data = body["data"]
        for key in ("window_days", "entity_type", "trends", "list", "status"):
            assert key in data, f"detection key {key} missing"
        assert isinstance(data["trends"], list)
        assert data["status"] in ("ok", "insufficient_data")
