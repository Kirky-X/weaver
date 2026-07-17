# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for briefings API endpoints (T009 / R-briefing-004, R-briefing-005).

Covers:
- GET /briefings/daily — fetch existing briefing by date + category
- POST /briefings/daily/generate — on-demand generation with narrative_mode param
- narrative_mode=True returns HTTP 501 (T009 挡板, T022 will remove)
- Router registration (prefix, tags, routes)

Patch surface: ``api.endpoints.briefings._get_briefing_service`` returns a mock
DailyBriefingService. Tests do NOT hit the real service/storage/LLM.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from api.endpoints.briefings import router
from modules.briefing.models import BriefingResult
from tests.helpers import create_test_client


def _make_briefing_result(
    *,
    briefing_date: date | None = None,
    category: str | None = "general",
    summary: str | None = "Daily summary text",
    items: list | None = None,
    briefing_id: int | None = 1,
) -> BriefingResult:
    """Build a BriefingResult fixture for tests."""
    return BriefingResult(
        date=briefing_date or date(2026, 7, 17),
        category=category,
        summary=summary,
        items=items or [],
        generated_at=datetime.now(UTC),
        narrative_mode=False,
        briefing_id=briefing_id,
    )


class TestBriefingsRouterRegistration:
    """Tests for briefings router registration."""

    def test_router_prefix(self) -> None:
        """Router prefix is /briefings."""
        assert router.prefix == "/briefings"

    def test_router_tags(self) -> None:
        """Router has 'briefings' tag."""
        assert "briefings" in router.tags

    def test_get_daily_route_exists(self) -> None:
        """GET /briefings/daily route is registered."""
        routes = [route.path for route in router.routes]
        assert "/briefings/daily" in routes

    def test_generate_daily_route_exists(self) -> None:
        """POST /briefings/daily/generate route is registered."""
        routes = [route.path for route in router.routes]
        assert "/briefings/daily/generate" in routes


class TestGetDailyBriefing:
    """Tests for GET /briefings/daily endpoint (R-briefing-004)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_get_daily_briefing_no_params_returns_null_data(self) -> None:
        """No params → default today + general, no briefing → data: null."""
        mock_service = MagicMock()
        mock_service.get_briefing = AsyncMock(return_value=None)

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.get("/briefings/daily")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert body["data"] is None
        mock_service.get_briefing.assert_called_once()

    def test_get_daily_briefing_with_date_and_category(self) -> None:
        """GET with date + category returns matching briefing."""
        mock_service = MagicMock()
        mock_service.get_briefing = AsyncMock(
            return_value=_make_briefing_result(category="finance")
        )

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.get("/briefings/daily?date=2026-07-17&category=finance")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["category"] == "finance"
        assert body["data"]["summary"] == "Daily summary text"
        assert body["data"]["narrative_mode"] is False

    def test_get_daily_briefing_forwards_date_and_category_to_service(self) -> None:
        """Endpoint forwards parsed date + category to service.get_briefing."""
        mock_service = MagicMock()
        mock_service.get_briefing = AsyncMock(return_value=None)

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            self.client.get("/briefings/daily?date=2026-07-17&category=tech")

        mock_service.get_briefing.assert_called_once_with(date=date(2026, 7, 17), category="tech")

    def test_get_daily_briefing_invalid_date_returns_422(self) -> None:
        """Invalid date format returns 422."""
        response = self.client.get("/briefings/daily?date=not-a-date")

        assert response.status_code == 422

    def test_get_daily_briefing_invalid_category_returns_422(self) -> None:
        """Invalid category value returns 422 (pattern validation)."""
        response = self.client.get("/briefings/daily?category=invalid")

        assert response.status_code == 422

    def test_get_daily_briefing_response_has_timestamp(self) -> None:
        """Response includes timestamp field."""
        mock_service = MagicMock()
        mock_service.get_briefing = AsyncMock(return_value=None)

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.get("/briefings/daily")

        body = response.json()
        assert "timestamp" in body

    def test_get_daily_briefing_serializes_briefing_id(self) -> None:
        """BriefingResult.briefing_id is serialized in response data."""
        mock_service = MagicMock()
        mock_service.get_briefing = AsyncMock(return_value=_make_briefing_result(briefing_id=42))

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.get("/briefings/daily?date=2026-07-17")

        body = response.json()
        assert body["data"]["briefing_id"] == 42

    def test_get_daily_briefing_service_error_returns_500(self) -> None:
        """Service error returns HTTP 500 (Rule 12: fail loud)."""
        mock_service = MagicMock()
        mock_service.get_briefing = AsyncMock(side_effect=RuntimeError("DB down"))

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.get("/briefings/daily?date=2026-07-17")

        assert response.status_code == 500
        body = response.json()
        assert "detail" in body


class TestGenerateDailyBriefing:
    """Tests for POST /briefings/daily/generate endpoint (R-briefing-005)."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_generate_daily_briefing_default_narrative_mode_false(self) -> None:
        """POST without narrative_mode defaults to False and generates."""
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(
            return_value=_make_briefing_result(category="finance")
        )

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post(
                "/briefings/daily/generate?date=2026-07-17&category=finance"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["category"] == "finance"
        # Service called with date + category (narrative_mode not yet forwarded
        # to service — T009 挡板: 501 on True, direct call on False).
        mock_service.generate_briefing.assert_called_once_with(
            date=date(2026, 7, 17), category="finance"
        )

    def test_generate_daily_briefing_narrative_mode_false_explicit(self) -> None:
        """POST with narrative_mode=false generates normally."""
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(return_value=_make_briefing_result())

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post(
                "/briefings/daily/generate?date=2026-07-17&narrative_mode=false"
            )

        assert response.status_code == 200
        mock_service.generate_briefing.assert_called_once()

    def test_generate_daily_briefing_narrative_mode_true_returns_501(self) -> None:
        """POST with narrative_mode=true returns 501 (T009 挡板, T022 removes).

        Before T021/T022 implement narrative mode, the endpoint MUST refuse
        with HTTP 501 Not Implemented and a clear message. This is a deliberate
        boundary (Rule 24: cover the scenario, not simplify it away).
        """
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(return_value=_make_briefing_result())

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post(
                "/briefings/daily/generate?date=2026-07-17&narrative_mode=true"
            )

        assert response.status_code == 501
        body = response.json()
        assert "detail" in body
        # Message must clearly indicate narrative mode is not implemented.
        detail = body["detail"]
        assert "narrative" in detail.lower() or "尚未实现" in detail
        # Service MUST NOT be called when 501 is returned.
        mock_service.generate_briefing.assert_not_called()

    def test_generate_daily_briefing_no_date_uses_today(self) -> None:
        """POST without date uses today's date."""
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(return_value=_make_briefing_result())

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post("/briefings/daily/generate")

        assert response.status_code == 200
        # Verify date forwarded is today.
        called_args = mock_service.generate_briefing.call_args
        assert called_args.kwargs["date"] == date.today()

    def test_generate_daily_briefing_invalid_category_returns_422(self) -> None:
        """POST with invalid category returns 422."""
        response = self.client.post("/briefings/daily/generate?category=invalid")

        assert response.status_code == 422

    def test_generate_daily_briefing_service_failure_returns_500(self) -> None:
        """Service failure returns HTTP 500 (R-briefing-005, Rule 12)."""
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post("/briefings/daily/generate?date=2026-07-17&category=ai")

        assert response.status_code == 500
        body = response.json()
        assert "detail" in body

    def test_generate_daily_briefing_response_has_timestamp(self) -> None:
        """POST response includes timestamp field."""
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(return_value=_make_briefing_result())

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post("/briefings/daily/generate")

        body = response.json()
        assert "timestamp" in body
