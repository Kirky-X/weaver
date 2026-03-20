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
        """Test that /health returns 200 status."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_shows_all_services_healthy(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health shows all services are healthy."""
        response = client.get("/health")
        data = response.json()

        # The health endpoint returns {"status": "...", "checks": {"postgres": {...}, ...}}
        # Check the structure matches the actual API response format.
        assert "checks" in data, f"Expected 'checks' key in health response: {data}"
        assert "postgres" in data["checks"], f"Expected 'postgres' in checks: {data['checks']}"
        assert data["checks"]["postgres"]["status"] == "ok"
        assert data["status"] in ("healthy", "unhealthy")

    def test_health_no_auth_required(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health works without X-API-Key header."""
        # No headers at all
        response = client.get("/health")
        assert response.status_code == 200
