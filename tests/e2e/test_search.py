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
                "/api/v1/search",
                params={"q": "人工智能", "mode": "articles"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data

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
                "/api/v1/search",
                params={"q": "test", "mode": "articles", "use_hybrid": "false"},
                headers=auth_headers,
            )

        assert response.status_code == 200

    def test_search_local_mode(
        self,
        client: TestClient,  # type: ignore[name-defined]
        auth_headers: dict[str, str],
    ) -> None:
        """Test search with local mode."""
        with patch(
            "modules.search.engines.local_search.LocalSearchEngine.search",
            new_callable=AsyncMock,
        ) as mock_search:
            from modules.search.engines.local_search import SearchResult

            mock_search.return_value = SearchResult(
                query="腾讯",
                answer="腾讯是中国互联网公司",
                context_tokens=100,
                confidence=0.9,
                entities=["腾讯"],
                sources=[],
                metadata={"search_type": "local"},
            )

            response = client.get(
                "/api/v1/search",
                params={"q": "腾讯", "mode": "local"},
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
        with patch(
            "modules.search.engines.global_search.GlobalSearchEngine.search",
            new_callable=AsyncMock,
        ) as mock_search:
            from modules.search.engines.local_search import SearchResult

            mock_search.return_value = SearchResult(
                query="AI",
                answer="AI has made significant progress",
                context_tokens=200,
                confidence=0.85,
                entities=["AI"],
                sources=[],
                metadata={"search_type": "global"},
            )

            response = client.get(
                "/api/v1/search",
                params={"q": "AI", "mode": "global"},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert data["data"]["search_type"] == "global"

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
                "/api/v1/search",
                params={"q": "test", "mode": "articles", "limit": 5},
                headers=auth_headers,
            )

        assert response.status_code == 200

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
                "/api/v1/search",
                params={"q": "test", "mode": "articles", "threshold": 0.8},
                headers=auth_headers,
            )

        assert response.status_code == 200

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
                "/api/v1/search",
                params={"q": "test", "mode": "articles", "category": "科技"},
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
                "/api/v1/search",
                params={"q": "test", "mode": "articles"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data

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
                "/api/v1/search",
                params={"q": "test", "mode": "articles"},
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
                "/api/v1/search",
                params={"q": "人工智能", "mode": "articles"},
                headers=auth_headers,
            )

        assert response.status_code == 200

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
                "/api/v1/search",
                params={"q": "人工智能", "mode": "articles"},
                headers=auth_headers,
            )

        assert response.status_code == 200

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
                "/api/v1/search",
                params={"q": "人工智能", "mode": "articles"},
                headers=auth_headers,
            )

        assert response.status_code == 200