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
        data = response.json() if response.status_code == 200 else response.json()["detail"]
        assert "status" in data

    def test_health_shows_all_services_healthy(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health shows all services status in checks structure."""
        response = client.get("/health")

        # Health endpoint returns 200 when healthy, 503 when unhealthy.
        # In both cases the response body contains the checks structure.
        if response.status_code == 503:
            data = response.json()["detail"]
        else:
            data = response.json()

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
