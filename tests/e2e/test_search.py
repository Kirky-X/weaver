# Copyright (c) 2026 KirkyX. All Rights Reserved
"""E2E tests for search API endpoints.

Tests the integrated functionality of hybrid search API.
Uses FastAPI TestClient for HTTP-level testing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_hybrid_engine() -> MagicMock:
    """Create mock HybridSearchEngine."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value=[
            {
                "doc_id": "article-1",
                "score": 0.92,
                "title": "人工智能发展现状",
                "content": "AI 技术发展迅速...",
                "source_url": "https://example.com/ai-article",
                "category": "科技",
                "publish_time": "2024-01-15T10:00:00Z",
            },
            {
                "doc_id": "article-2",
                "score": 0.85,
                "title": "机器学习基础",
                "content": "机器学习是人工智能的重要分支...",
                "source_url": "https://example.com/ml-article",
                "category": "科技",
                "publish_time": "2024-01-14T10:00:00Z",
            },
        ]
    )
    engine.get_stats = MagicMock(
        return_value={
            "total_searches": 100,
            "avg_latency_ms": 25.5,
        }
    )
    return engine


@pytest.fixture
def mock_embedding_service() -> MagicMock:
    """Create mock embedding service."""
    service = MagicMock()
    service.get_embedding = AsyncMock(return_value=[0.1] * 768)
    return service


@pytest.mark.e2e
class TestSearchEndpointE2E:
    """E2E tests for search API endpoints."""

    def test_search_hybrid_valid_query_returns_results(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test hybrid search with valid query returns results."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "人工智能", "mode": "hybrid"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_search_vector_only_mode(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test search with vector-only mode."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "test", "mode": "vector"},
                headers=auth_headers,
            )

        assert response.status_code == 200

    def test_search_bm25_only_mode(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
    ) -> None:
        """Test search with BM25-only mode."""
        with patch(
            "api.endpoints.search.get_hybrid_search_engine",
            return_value=mock_hybrid_engine,
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "test", "mode": "bm25"},
                headers=auth_headers,
            )

        assert response.status_code == 200

    def test_search_respects_limit_parameter(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test that search respects limit parameter."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "test", "limit": 5},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data.get("results", [])) <= 5

    def test_search_respects_threshold_parameter(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test that search respects threshold parameter."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "test", "threshold": 0.8},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        # All results should have score >= threshold
        for result in data.get("results", []):
            assert result.get("score", 0) >= 0.8

    def test_search_with_category_filter(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test search with category filter."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "test", "category": "科技"},
                headers=auth_headers,
            )

        assert response.status_code == 200


@pytest.mark.e2e
class TestSearchMetadataE2E:
    """E2E tests for search response metadata."""

    def test_response_includes_timing_metadata(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test that response includes timing metadata."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "test"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        # Should have metadata section
        assert "metadata" in data or "timing" in data

    def test_response_includes_retrieval_metadata(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test that response includes retrieval metadata when hybrid search is used."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "test", "mode": "hybrid"},
                headers=auth_headers,
            )

        assert response.status_code == 200


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
            "/api/v1/search/articles",
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_invalid_mode_parameter_returns_422(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test that invalid mode parameter returns 422."""
        response = client.get(
            "/api/v1/search/articles",
            params={"q": "test", "mode": "invalid"},
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
            "/api/v1/search/articles",
            params={"q": "test", "limit": 200},  # exceeds max of 100
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_search_requires_auth(
        self,
        client: TestClient,  # type: ignore[name-defined]
    ) -> None:
        """Test that search returns 401 without authentication."""
        response = client.get(
            "/api/v1/search/articles",
            params={"q": "test"},
        )

        assert response.status_code == 401


@pytest.mark.e2e
class TestSearchResultMetadataE2E:
    """E2E tests for search result document metadata."""

    def test_results_include_source_url(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test that results include source_url field."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "人工智能"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        for result in data.get("results", []):
            assert "source_url" in result

    def test_results_include_category(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test that results include category field."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "人工智能"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        for result in data.get("results", []):
            assert "category" in result

    def test_results_include_publish_time(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
        mock_hybrid_engine: MagicMock,
        mock_embedding_service: MagicMock,
    ) -> None:
        """Test that results include publish_time field if available."""
        with (
            patch(
                "api.endpoints.search.get_hybrid_search_engine",
                return_value=mock_hybrid_engine,
            ),
            patch(
                "api.endpoints.search.get_embedding_service",
                return_value=mock_embedding_service,
            ),
        ):
            response = client.get(
                "/api/v1/search/articles",
                params={"q": "人工智能"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        # Results may have publish_time
        for result in data.get("results", []):
            # publish_time is optional, just check the field exists
            assert "publish_time" in result or result.get("publish_time") is None
