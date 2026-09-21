# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""E2E tests for API user flows.

Tests complete user workflows through the real API:
1. Article browsing flow (list → detail)
2. Search flow (unified endpoint with explicit modes)
3. Analytics/monitoring flow

These tests use the real FastAPI application and real database connections.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.helpers import assert_api_response


@pytest.mark.e2e
class TestArticleProcessingFlow:
    """Test complete article browsing workflow via real API."""

    def test_article_list_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test listing articles via real API endpoint (page/page_size params)."""
        response = client.get(
            "/api/v1/articles",
            headers=auth_headers,
            params={"page": 1, "page_size": 10},
        )

        data = assert_api_response(response)
        assert "items" in data.get("data", {})

    def test_article_detail_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test getting article detail via real API endpoint (data.items)."""
        list_response = client.get(
            "/api/v1/articles",
            headers=auth_headers,
            params={"page": 1, "page_size": 1},
        )

        list_data = assert_api_response(list_response)
        articles = list_data.get("data", {}).get("items", [])

        if len(articles) == 0:
            pytest.skip("No articles available for detail test")

        article_id = articles[0]["id"]

        detail_response = client.get(
            f"/api/v1/articles/{article_id}",
            headers=auth_headers,
        )

        detail_data = assert_api_response(detail_response)
        assert detail_data["data"]["id"] == article_id


@pytest.mark.e2e
class TestSearchFlow:
    """Test search workflow via real API (unified endpoint, q parameter)."""

    def test_global_search_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test global search mode; 503 is the documented degraded outcome."""
        response = client.get(
            "/api/v1/search",
            headers=auth_headers,
            params={"q": "test", "mode": "global", "limit": 5},
        )

        assert response.status_code in (200, 503), f"Search failed: {response.text}"
        data = response.json()
        assert "code" in data
        if response.status_code == 200:
            assert data["data"]["search_type"] == "global"

    def test_local_search_endpoint(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test local search mode; 503 is the documented degraded outcome."""
        response = client.get(
            "/api/v1/search",
            headers=auth_headers,
            params={"q": "test", "mode": "local", "limit": 5},
        )

        assert response.status_code in (200, 503), f"Local search failed: {response.text}"
        data = response.json()
        assert "code" in data
        if response.status_code == 200:
            assert data["data"]["search_type"] == "local"


@pytest.mark.e2e
class TestAnalyticsFlow:
    """Test analytics/monitoring workflow via real API."""

    def test_llm_usage_endpoint(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """LLM usage lives at /monitoring/llm/usage and requires admin + from/to."""
        to_date = datetime.now().isoformat()
        from_date = (datetime.now() - timedelta(days=7)).isoformat()
        response = client.get(
            "/api/v1/monitoring/llm/usage",
            headers=admin_headers,
            params={"from": from_date, "to": to_date, "group_by": "model"},
        )

        assert response.status_code == 200, f"LLM usage failed: {response.text}"
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["group_by"] == "model"

    def test_community_analytics_endpoint(
        self,
        client: TestClient,
        admin_headers: dict[str, str],
    ) -> None:
        """Community analytics is the admin communities health overview."""
        response = client.get(
            "/api/v1/admin/communities/health",
            headers=admin_headers,
        )

        assert response.status_code == 200, f"Community health failed: {response.text}"
        data = response.json()
        assert data["code"] == 0
        assert "score" in data["data"]
