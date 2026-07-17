# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for briefings API endpoints (T009 / T022 / R-briefing-004, R-briefing-005).

Covers:
- GET /briefings/daily — fetch existing briefing by date + category
- POST /briefings/daily/generate — on-demand generation with narrative_mode param
- narrative_mode=true forwards to service.generate_briefing(narrative_mode=True)
  (T022 removed the T009 501 挡板)
- narrative_mode=true without narrative_generator → 503 (T022 fail-loud)
- Other ValueError (invalid category) → 400 (T022 client error)
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
    narrative_mode: bool = False,
) -> BriefingResult:
    """Build a BriefingResult fixture for tests."""
    return BriefingResult(
        date=briefing_date or date(2026, 7, 17),
        category=category,
        summary=summary,
        items=items or [],
        generated_at=datetime.now(UTC),
        narrative_mode=narrative_mode,
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
        """POST without narrative_mode defaults to False and generates (T022)."""
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
        # T022: narrative_mode is forwarded to service (default False).
        mock_service.generate_briefing.assert_called_once_with(
            date=date(2026, 7, 17), category="finance", narrative_mode=False
        )

    def test_generate_daily_briefing_narrative_mode_false_explicit(self) -> None:
        """POST with narrative_mode=false forwards to service with narrative_mode=False."""
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(return_value=_make_briefing_result())

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post(
                "/briefings/daily/generate?date=2026-07-17&narrative_mode=false"
            )

        assert response.status_code == 200
        mock_service.generate_briefing.assert_called_once_with(
            date=date(2026, 7, 17), category=None, narrative_mode=False
        )

    def test_generate_daily_briefing_narrative_mode_true_forwards_to_service(self) -> None:
        """POST with narrative_mode=true forwards to service with narrative_mode=True (T022).

        T022 removes the T009 501 挡板: narrative_mode is transparently
        forwarded to DailyBriefingService.generate_briefing(narrative_mode=True).
        Service layer (T021) handles routing + degradation.
        """
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(
            return_value=_make_briefing_result(category="finance", narrative_mode=True)
        )

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post(
                "/briefings/daily/generate?date=2026-07-17&category=finance&narrative_mode=true"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        # Service called with narrative_mode=True (T022 forwarding).
        mock_service.generate_briefing.assert_called_once_with(
            date=date(2026, 7, 17), category="finance", narrative_mode=True
        )
        # BriefingResult.narrative_mode=True reflected in response (T021 contract).
        assert body["data"]["narrative_mode"] is True

    def test_generate_daily_briefing_narrative_mode_unavailable_returns_503(self) -> None:
        """narrative_mode=true without narrative_generator → 503 (T022, R-briefing-008).

        Service raises ValueError when narrative_mode=True but narrative_generator
        is None (graph_pool unavailable). Handler maps to 503 so caller can
        retry with narrative_mode=false (Rule 12 fail-loud + actionable).
        """
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(
            side_effect=ValueError(
                "narrative_mode=True requested but narrative_generator is None. "
                "Caller must inject NarrativeBriefingGenerator when constructing "
                "DailyBriefingService to use narrative mode (R-briefing-008)."
            )
        )

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post(
                "/briefings/daily/generate?date=2026-07-17&narrative_mode=true"
            )

        assert response.status_code == 503
        body = response.json()
        assert "detail" in body
        detail = body["detail"]
        # Actionable message: tells caller to retry with false or start graph pool.
        assert "narrative" in detail.lower() or "graph pool" in detail.lower()

    def test_generate_daily_briefing_invalid_category_value_error_returns_400(self) -> None:
        """ValueError from invalid category (not narrative_generator) → 400 (T022).

        Handler distinguishes:
        - ValueError containing 'narrative_generator' → 503 (service unavailable)
        - Other ValueError (invalid category, etc.) → 400 (client error)
        """
        mock_service = MagicMock()
        mock_service.generate_briefing = AsyncMock(
            side_effect=ValueError("Invalid category 'sports'")
        )

        with patch("api.endpoints.briefings._get_briefing_service", return_value=mock_service):
            response = self.client.post(
                "/briefings/daily/generate?date=2026-07-17&category=finance"
            )

        assert response.status_code == 400
        body = response.json()
        assert "detail" in body

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
