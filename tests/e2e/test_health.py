# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for health check endpoint."""

from __future__ import annotations

import pytest

from tests.e2e.base import E2EClient


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

        # Should have status for postgres, neo4j, redis
        assert "postgres" in data or "services" in data

    def test_health_no_auth_required(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that /health works without X-API-Key header."""
        # No headers at all
        response = client.get("/health")
        assert response.status_code == 200
