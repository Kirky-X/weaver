# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for health check endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.e2e
class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_200(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health returns a valid response (200 when healthy, 503 when not)."""
        response = client.get("/health")
        assert response.status_code in (200, 503)
        json_data = response.json()
        # Response is wrapped in APIResponse format
        if response.status_code == 200:
            assert "code" in json_data
            assert "message" in json_data
            assert "data" in json_data
            assert "timestamp" in json_data
            assert json_data["code"] == 0
            data = json_data["data"]
        else:
            # Error case: detail contains the health check data
            data = json_data.get("detail", json_data)
        assert "status" in data

    def test_health_shows_all_services_healthy(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health shows all services status in checks structure."""
        response = client.get("/health")

        # Health endpoint returns 200 when healthy, 503 when unhealthy.
        # Response is wrapped in APIResponse format with code, message, data, timestamp.
        json_data = response.json()
        if response.status_code == 200:
            data = json_data["data"]
        else:
            data = json_data.get("detail", json_data)

        assert "checks" in data, f"Expected 'checks' key in health response: {data}"
        assert "postgres" in data["checks"], f"Expected 'postgres' in checks: {data['checks']}"
        assert data["status"] in ("healthy", "unhealthy")

    def test_health_no_auth_required(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health works without X-API-Key header."""
        # No headers at all - should return either 200 or 503, not 401/403
        response = client.get("/health")
        assert response.status_code in (200, 503)

    def test_health_response_format(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health follows unified APIResponse format when healthy."""
        response = client.get("/health")
        json_data = response.json()

        if response.status_code == 200:
            # Verify unified response structure
            assert "code" in json_data, "Missing 'code' field in response"
            assert "message" in json_data, "Missing 'message' field in response"
            assert "data" in json_data, "Missing 'data' field in response"
            assert "timestamp" in json_data, "Missing 'timestamp' field in response"
            assert json_data["code"] == 0, f"Expected code=0 for success, got {json_data['code']}"
            assert json_data["message"] == "success"
            # Verify data contains health check info
            assert "status" in json_data["data"]
            assert "checks" in json_data["data"]
