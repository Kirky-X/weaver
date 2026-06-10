# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for analytics API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints.analytics import router


def _mock_auth(app: FastAPI) -> None:
    """Override verify_api_key dependency to bypass auth in tests."""
    from api.middleware.auth import verify_api_key

    app.dependency_overrides[verify_api_key] = lambda: "test-key"


class TestAnalyticsShiftsEndpoint:
    """Tests for /analytics/shifts endpoint."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.app = FastAPI()
        self.app.include_router(router)
        _mock_auth(self.app)
        self.client = TestClient(self.app)

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
        self.app = FastAPI()
        self.app.include_router(router)
        _mock_auth(self.app)
        self.client = TestClient(self.app)

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
        self.app = FastAPI()
        self.app.include_router(router)
        _mock_auth(self.app)
        self.client = TestClient(self.app)

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
        self.app = FastAPI()
        self.app.include_router(router)
        _mock_auth(self.app)
        self.client = TestClient(self.app)

    def test_briefings_endpoint_returns_data(self) -> None:
        """Test briefings endpoint returns data from storage."""
        mock_pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_pool.session_context.return_value = mock_session

        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.briefing_date = "2026-01-15"
        mock_row.total_items = 5
        mock_row.generated_at = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_storage = MagicMock()
        mock_storage._pool = mock_pool

        with patch("api.endpoints.analytics._get_analytics_storage", return_value=mock_storage):
            response = self.client.get("/analytics/briefings")

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["total"] == 1
        assert len(body["data"]["briefings"]) == 1

    def test_briefings_endpoint_handles_storage_error(self) -> None:
        """Test briefings endpoint handles storage errors gracefully."""
        mock_storage = MagicMock()
        mock_storage._pool = MagicMock()
        mock_storage._pool.session_context.side_effect = Exception("DB error")

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
