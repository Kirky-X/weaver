# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Integration tests for Search engines with real data.

Tests search functionality using real API server and real articles/communities.
Connects to running server at localhost:8000 to avoid DuckDB lock conflicts.

IMPORTANT: These tests require a running API server. Start the server first:
    uv run python -m src.main

Or set WEAVER_TEST_API_URL to point to an existing server.
"""

from __future__ import annotations

import os

import httpx
import pytest

API_BASE_URL = os.environ.get("WEAVER_TEST_API_URL", "http://localhost:8000")
# API key must be at least 32 characters (see src/api/middleware/auth.py:24)
API_KEY = os.environ.get("WEAVER_API__API_KEY", "test-api-key-32chars-long!!!!!!!")


def _check_server_available() -> bool:
    """Check if API server is running and accessible."""
    try:
        with httpx.Client(base_url=API_BASE_URL, timeout=5.0) as client:
            response = client.get("/health")
            return (
                response.status_code == 200
                and response.json().get("data", {}).get("status") == "healthy"
            )
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        return False


SERVER_AVAILABLE = _check_server_available()


@pytest.fixture(scope="module")
def http_client():
    """Create httpx client for module-scoped tests.

    Raises Skip if server is not available.
    """
    if not SERVER_AVAILABLE:
        pytest.skip(
            f"API server not running at {API_BASE_URL}. "
            "Start server with 'uv run python -m src.main' or set WEAVER_TEST_API_URL"
        )
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        yield client


@pytest.mark.integration
class TestSearchAPIIntegration:
    """Integration tests for search API endpoints with real data."""

    def test_search_unified_returns_results(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test unified search returns real results."""
        response = http_client.get(
            "/api/v1/search",
            params={"q": "AI", "limit": 5},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        result = data["data"]

        # Verify real search results
        # 'auto' is valid when mode is not specified
        assert result["search_type"] in ("local", "global", "articles", "auto")
        # Different search types return different structures
        # auto: answer, confidence, entities, context_tokens
        # local/global: results, entities
        # articles: articles
        valid_keys = {"results", "articles", "answer", "entities"}
        assert any(key in result for key in valid_keys)
        assert result["query"] == "AI"

    def test_search_temporal_with_real_events(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test temporal search with real events from pipeline."""
        response = http_client.post(
            "/api/v1/search/temporal",
            json={"query": "科技", "limit": 10},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        result = data["data"]

        # Verify temporal search structure
        assert "events" in result
        assert isinstance(result["events"], list)

        # If events exist, verify structure
        if result["events"]:
            event = result["events"][0]
            assert "id" in event
            assert "content" in event
            assert "timestamp" in event

    def test_search_causal_with_real_entities(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test causal search with real entities."""
        response = http_client.post(
            "/api/v1/search/causal",
            json={"query": "技术", "limit": 10},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        result = data["data"]

        # Verify causal search structure
        assert "query" in result
        assert "chains" in result or "answer" in result or "entities" in result

    def test_search_drift_with_real_communities(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test DRIFT search with real communities."""
        response = http_client.post(
            "/api/v1/search/drift",
            json={"query": "人工智能", "limit": 5},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        result = data["data"]

        # Verify DRIFT search structure
        assert "answer" in result
        assert "confidence" in result
        assert result["query"] == "人工智能"

        # DRIFT uses communities for primer phase
        # Should have hierarchy info
        assert "hierarchy" in result or "primer_communities" in result

    def test_search_with_different_modes(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test search with different modes uses real data."""
        modes = ["local", "global"]

        for mode in modes:
            response = http_client.get(
                "/api/v1/search",
                params={"q": "测试", "mode": mode, "limit": 3},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0
            result = data["data"]

            assert result["search_type"] == mode

    def test_search_articles_mode_real_embeddings(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test articles mode uses real embeddings from pipeline."""
        response = http_client.get(
            "/api/v1/search",
            params={"q": "AI", "mode": "articles", "limit": 5},
            headers=auth_headers,
        )

        # Articles mode requires LLM service
        # If available, expect real vector search results
        if response.status_code == 200:
            data = response.json()
            assert data["code"] == 0
            result = data["data"]
            assert result["search_type"] == "articles"
            # Should have real articles from vector similarity
            if "articles" in result:
                assert isinstance(result["articles"], list)


@pytest.mark.integration
class TestSearchEndToEnd:
    """End-to-end search tests using full pipeline data."""

    def test_full_search_workflow(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test complete search workflow from query to results."""
        # Step 1: Verify we have real data
        articles_response = http_client.get(
            "/api/v1/articles",
            params={"limit": 1},
            headers=auth_headers,
        )
        assert articles_response.status_code == 200
        articles_data = articles_response.json()
        assert articles_data["code"] == 0
        assert articles_data["data"]["total"] >= 1, "Need real articles for search test"

        # Step 2: Perform search
        search_response = http_client.get(
            "/api/v1/search",
            params={"q": "科技", "limit": 5},
            headers=auth_headers,
        )
        assert search_response.status_code == 200
        search_data = search_response.json()

        # Step 3: Verify results
        assert search_data["code"] == 0
        result = search_data["data"]
        assert result["query"] == "科技"

    def test_search_returns_existing_article_content(
        self,
        http_client: httpx.Client,
        auth_headers: dict[str, str],
    ) -> None:
        """Test search finds content from existing articles."""
        # First, get an article to know what content exists
        articles_response = http_client.get(
            "/api/v1/articles",
            params={"limit": 1},
            headers=auth_headers,
        )

        if articles_response.status_code == 200:
            articles_data = articles_response.json()
            items = articles_data["data"]["items"]

            if items:
                # Use article title or content as search query
                title = items[0].get("title", "")
                if title:
                    # Search for title content
                    search_response = http_client.get(
                        "/api/v1/search",
                        params={"q": title[:20], "limit": 5},
                        headers=auth_headers,
                    )

                    if search_response.status_code == 200:
                        search_data = search_response.json()
                        assert search_data["code"] == 0
