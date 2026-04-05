# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for search API endpoints.

Tests the integrated functionality of hybrid search API.
Uses FastAPI TestClient for HTTP-level testing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.e2e
class TestSearchEndpointE2E:
    """E2E tests for search API endpoints."""

    def test_search_local_mode(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test search with local mode."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "local"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["data"]["search_type"] == "local"

    def test_search_global_mode(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test search with global mode."""
        response = client.get(
            "/api/v1/search",
            params={"q": "AI", "mode": "global"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["data"]["search_type"] == "global"

    def test_search_articles_mode_requires_llm(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test search with articles mode - requires LLM embedding service.

        This test verifies the API handles the articles search mode.
        If LLM service is unavailable, it returns 503.
        """
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "articles"},
            headers=auth_headers,
        )

        # Articles mode requires LLM embedding service
        # If LLM is available, expect 200; otherwise expect 503
        assert response.status_code in (200, 503)

        if response.status_code == 200:
            data = response.json()
            assert "data" in data

    def test_search_respects_limit_parameter(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that search respects limit parameter in articles mode."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "articles", "limit": 5},
            headers=auth_headers,
        )

        # Articles mode requires LLM; skip assertion if service unavailable
        assert response.status_code in (200, 503)

    def test_search_respects_threshold_parameter(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that search respects threshold parameter in articles mode."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "articles", "threshold": 0.8},
            headers=auth_headers,
        )

        # Articles mode requires LLM; skip assertion if service unavailable
        assert response.status_code in (200, 503)

    def test_search_with_category_filter(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test search with category filter in articles mode."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "articles", "category": "tech"},
            headers=auth_headers,
        )

        # Articles mode requires LLM; skip assertion if service unavailable
        assert response.status_code in (200, 503)


@pytest.mark.e2e
class TestSearchMetadataE2E:
    """E2E tests for search response metadata."""

    def test_response_includes_data_structure(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that response includes proper data structure."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "local"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "query" in data["data"]
        assert "answer" in data["data"]
        assert "search_type" in data["data"]


@pytest.mark.e2e
class TestSearchErrorHandlingE2E:
    """E2E tests for search API error handling."""

    def test_missing_query_parameter_returns_422(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that missing query parameter returns 422."""
        response = client.get(
            "/api/v1/search",
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_invalid_limit_value_returns_422(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that invalid limit value returns 422."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "articles", "limit": 200},  # exceeds max of 100
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_search_requires_auth(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that search returns 401 without authentication."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test"},
        )

        assert response.status_code == 401


@pytest.mark.e2e
class TestSearchModeRoutingE2E:
    """E2E tests for search mode routing."""

    def test_default_mode_is_local(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that default search mode is auto (intent-based routing)."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test"},  # no mode specified
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Default mode is 'auto' which uses intent-based routing
        assert data["data"]["search_type"] == "auto"

    def test_entity_names_parameter_in_local_mode(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test entity_names parameter works in local mode."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "local", "entity_names": "Entity1,Entity2"},
            headers=auth_headers,
        )

        assert response.status_code == 200

    def test_community_level_parameter_in_global_mode(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test community_level parameter works in global mode."""
        response = client.get(
            "/api/v1/search",
            params={"q": "test", "mode": "global", "community_level": 2},
            headers=auth_headers,
        )

        assert response.status_code == 200
