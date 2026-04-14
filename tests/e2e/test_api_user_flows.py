# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for API user flows.

Tests complete user workflows through the real API:
1. Article processing flow
2. Search and retrieval flow
3. Entity management flow
4. Analytics flow

These tests use:
- Real FastAPI application
- Real database connections
- Real API endpoints
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import assert_api_response


@pytest.mark.e2e
class TestArticleProcessingFlow:
    """Test complete article processing workflow via real API."""

    def test_article_list_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test listing articles via real API endpoint."""
        response = client.get(
            "/api/v1/admin/articles",
            headers=auth_headers,
            params={"limit": 10, "offset": 0},
        )

        data = assert_api_response(response)
        assert "articles" in data.get("data", {})

    def test_article_detail_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting article detail via real API endpoint."""
        list_response = client.get(
            "/api/v1/admin/articles",
            headers=auth_headers,
            params={"limit": 1},
        )

        list_data = assert_api_response(list_response)
        articles = list_data.get("data", {}).get("articles", [])

        if len(articles) == 0:
            pytest.skip("No articles available for detail test")

        article_id = articles[0]["id"]

        detail_response = client.get(
            f"/api/v1/admin/articles/{article_id}",
            headers=auth_headers,
        )

        detail_data = assert_api_response(detail_response)
        assert detail_data["data"]["id"] == article_id


@pytest.mark.e2e
class TestSearchFlow:
    """Test search workflow via real API."""

    def test_global_search_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test global search endpoint."""
        response = client.get(
            "/api/v1/search/global",
            headers=auth_headers,
            params={"query": "test", "limit": 5},
        )

        assert response.status_code == 200, f"Search failed: {response.text}"

        data = response.json()
        assert "data" in data

    def test_local_search_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test local search endpoint."""
        response = client.get(
            "/api/v1/search/local",
            headers=auth_headers,
            params={"query": "test", "limit": 5},
        )

        assert response.status_code == 200, f"Local search failed: {response.text}"

        data = response.json()
        assert "data" in data


@pytest.mark.e2e
class TestEntityManagementFlow:
    """Test entity management workflow via real API."""

    def test_entity_list_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test listing entities via real API."""
        response = client.get(
            "/api/v1/admin/entities",
            headers=auth_headers,
            params={"limit": 10},
        )

        assert response.status_code == 200, f"Entity list failed: {response.text}"

        data = response.json()
        assert "data" in data

    def test_entity_type_filter(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test filtering entities by type."""
        response = client.get(
            "/api/v1/admin/entities",
            headers=auth_headers,
            params={"entity_type": "PERSON", "limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data


@pytest.mark.e2e
class TestAnalyticsFlow:
    """Test analytics workflow via real API."""

    def test_llm_usage_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test LLM usage analytics endpoint."""
        response = client.get(
            "/api/v1/admin/llm-usage",
            headers=auth_headers,
            params={"group_by": "model", "limit": 10},
        )

        assert response.status_code == 200, f"LLM usage failed: {response.text}"

        data = response.json()
        assert "data" in data

    def test_community_analytics_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test community analytics endpoint."""
        response = client.get(
            "/api/v1/admin/communities/stats",
            headers=auth_headers,
        )

        assert response.status_code in (200, 404), f"Community stats failed: {response.text}"

        if response.status_code == 200:
            data = response.json()
            assert "data" in data
