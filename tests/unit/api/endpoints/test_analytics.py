# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for analytics API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from api.endpoints.analytics import router
from tests.helpers import create_test_client


class TestAnalyticsShiftsEndpoint:
    """Tests for /analytics/shifts endpoint."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_get_shifts_returns_success_response(self) -> None:
        """Test that shifts endpoint returns success response."""
        response = self.client.get("/analytics/shifts")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert body["data"]["shifts"] == []
        assert body["data"]["total"] == 0

    def test_get_shifts_with_community_id_param(self) -> None:
        """Test that shifts endpoint accepts community_id parameter."""
        response = self.client.get("/analytics/shifts?community_id=test-community")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    def test_get_shifts_with_limit_param(self) -> None:
        """Test that shifts endpoint accepts limit parameter."""
        response = self.client.get("/analytics/shifts?limit=10")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    def test_get_shifts_with_all_params(self) -> None:
        """Test that shifts endpoint accepts all parameters."""
        response = self.client.get("/analytics/shifts?community_id=test-community&limit=25")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    def test_get_shifts_limit_too_large(self) -> None:
        """Test that shifts endpoint rejects too large limit."""
        response = self.client.get("/analytics/shifts?limit=1000")

        assert response.status_code == 422

    def test_get_shifts_limit_zero(self) -> None:
        """Test that shifts endpoint rejects zero limit."""
        response = self.client.get("/analytics/shifts?limit=0")

        assert response.status_code == 422

    def test_get_shifts_response_has_timestamp(self) -> None:
        """Test that response includes timestamp."""
        response = self.client.get("/analytics/shifts")

        body = response.json()
        assert "timestamp" in body


class TestAnalyticsBriefingsEndpoint:
    """Tests for /analytics/briefings endpoint."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_get_briefings_returns_success_response(self) -> None:
        """Test that briefings endpoint returns success response."""
        response = self.client.get("/analytics/briefings")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["message"] == "success"
        assert body["data"]["briefings"] == []
        assert body["data"]["total"] == 0

    def test_get_briefings_with_date_param(self) -> None:
        """Test that briefings endpoint accepts date parameter."""
        response = self.client.get("/analytics/briefings?date=2026-01-15")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    def test_get_briefings_with_limit_param(self) -> None:
        """Test that briefings endpoint accepts limit parameter."""
        response = self.client.get("/analytics/briefings?limit=5")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    def test_get_briefings_with_all_params(self) -> None:
        """Test that briefings endpoint accepts all parameters."""
        response = self.client.get("/analytics/briefings?date=2026-01-15&limit=5")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    def test_get_briefings_limit_too_large(self) -> None:
        """Test that briefings endpoint rejects too large limit."""
        response = self.client.get("/analytics/briefings?limit=200")

        assert response.status_code == 422

    def test_get_briefings_limit_zero(self) -> None:
        """Test that briefings endpoint rejects zero limit."""
        response = self.client.get("/analytics/briefings?limit=0")

        assert response.status_code == 422

    def test_get_briefings_response_has_timestamp(self) -> None:
        """Test that response includes timestamp."""
        response = self.client.get("/analytics/briefings")

        body = response.json()
        assert "timestamp" in body


class TestAnalyticsShiftsWithData:
    """Tests for /analytics/shifts endpoint with actual storage data."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_shifts_endpoint_returns_data(self) -> None:
        """Test shifts endpoint returns data from storage."""
        mock_storage = MagicMock()
        mock_storage.get_shifts = AsyncMock(
            return_value=[
                {
                    "community_id": "comm-1",
                    "shift_type": "gradual",
                    "direction": "positive",
                    "magnitude": 0.15,
                    "confidence": 0.85,
                }
            ]
        )

        with patch("api.endpoints.analytics._get_analytics_storage", return_value=mock_storage):
            response = self.client.get("/analytics/shifts")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["total"] == 1
        assert len(body["data"]["shifts"]) == 1

    def test_shifts_endpoint_handles_storage_error(self) -> None:
        """Test shifts endpoint handles storage errors gracefully."""
        with patch(
            "api.endpoints.analytics._get_analytics_storage",
            side_effect=Exception("Storage unavailable"),
        ):
            response = self.client.get("/analytics/shifts")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["shifts"] == []
        assert body["data"]["total"] == 0


class TestAnalyticsBriefingsWithData:
    """Tests for /analytics/briefings endpoint with actual storage data."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.client = create_test_client(router)

    def test_briefings_endpoint_returns_data(self) -> None:
        """Test briefings endpoint returns data from storage."""
        mock_storage = MagicMock()
        mock_storage.get_briefings_with_items = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "briefing_date": "2026-01-15",
                    "title": "Daily Briefing",
                    "summary": "Summary",
                    "status": "published",
                    "total_items": 5,
                    "generated_at": None,
                    "items": [],
                }
            ]
        )

        with patch("api.endpoints.analytics._get_analytics_storage", return_value=mock_storage):
            response = self.client.get("/analytics/briefings")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["total"] == 1
        assert len(body["data"]["briefings"]) == 1
        mock_storage.get_briefings_with_items.assert_called_once_with(date=None, limit=10)

    def test_briefings_endpoint_handles_storage_error(self) -> None:
        """Test briefings endpoint handles storage errors gracefully.

        AnalyticsStorage.get_briefings_with_items logs and returns [] on error,
        so the endpoint receives an empty list rather than raising.
        """
        mock_storage = MagicMock()
        mock_storage.get_briefings_with_items = AsyncMock(return_value=[])

        with patch("api.endpoints.analytics._get_analytics_storage", return_value=mock_storage):
            response = self.client.get("/analytics/briefings")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["briefings"] == []
        assert body["data"]["total"] == 0


class TestAnalyticsRouterRegistration:
    """Tests for analytics router registration."""

    def test_router_prefix(self) -> None:
        """Test that router has correct prefix."""
        assert router.prefix == "/analytics"

    def test_router_tags(self) -> None:
        """Test that router has correct tags."""
        assert "analytics" in router.tags

    def test_shifts_route_exists(self) -> None:
        """Test that shifts route is registered."""
        routes = [route.path for route in router.routes]
        assert "/analytics/shifts" in routes

    def test_briefings_route_exists(self) -> None:
        """Test that briefings route is registered."""
        routes = [route.path for route in router.routes]
        assert "/analytics/briefings" in routes
