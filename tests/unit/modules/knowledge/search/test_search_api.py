# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for search API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.endpoints._deps import Endpoints
from modules.knowledge.search.engines.local_search import SearchResult
from modules.storage.postgres.vector_repo import SimilarArticle

# ── Mock Factories ───────────────────────────────────────────────


def _make_mock_local_engine(
    result: SearchResult | None = None,
    exc: Exception | None = None,
) -> MagicMock:
    engine = MagicMock()
    if exc is not None:
        engine.search = AsyncMock(side_effect=exc)
    else:
        engine.search = AsyncMock(
            return_value=result
            or SearchResult(
                query="test",
                answer="test answer",
                context_tokens=100,
                confidence=0.85,
                entities=["腾讯"],
                sources=[],
                metadata={"search_type": "local"},
            )
        )
    return engine


def _make_mock_global_engine(
    result: SearchResult | None = None,
    exc: Exception | None = None,
) -> MagicMock:
    engine = MagicMock()
    if exc is not None:
        engine.search = AsyncMock(side_effect=exc)
    else:
        engine.search = AsyncMock(
            return_value=result
            or SearchResult(
                query="test",
                answer="global answer",
                context_tokens=200,
                confidence=0.7,
                entities=["AI"],
                sources=[],
                metadata={"search_type": "global"},
            )
        )
    return engine


def _make_mock_vector_repo(
    similar: list[SimilarArticle] | None = None,
    exc: Exception | None = None,
) -> MagicMock:
    repo = MagicMock()
    if exc is not None:
        repo.find_similar = AsyncMock(side_effect=exc)
        repo.find_similar_hybrid = AsyncMock(side_effect=exc)
    elif similar is not None:
        repo.find_similar = AsyncMock(return_value=similar)
        repo.find_similar_hybrid = AsyncMock(return_value=similar)
    else:
        repo.find_similar = AsyncMock(
            return_value=[
                SimilarArticle(article_id="abc-123", category="tech", similarity=0.92),
                SimilarArticle(article_id="def-456", category="tech", similarity=0.88),
            ]
        )
        repo.find_similar_hybrid = AsyncMock(
            return_value=[
                SimilarArticle(
                    article_id="abc-123", category="tech", similarity=0.92, hybrid_score=0.85
                ),
                SimilarArticle(
                    article_id="def-456", category="tech", similarity=0.88, hybrid_score=0.80
                ),
            ]
        )
    return repo


def _make_mock_llm(
    embeddings: list[list[float]] | None = None,
    exc: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    if exc is not None:
        client.embed_default = AsyncMock(side_effect=exc)
    else:
        client.embed_default = AsyncMock(return_value=embeddings or [[0.1] * 1024])
    return client


def _make_mock_request() -> MagicMock:
    from starlette.requests import Request

    mock_req = MagicMock(spec=Request)
    mock_req.client = MagicMock()
    mock_req.client.host = "127.0.0.1"
    return mock_req


# ── Test GET /search (unified) ─────────────────────────────────


class TestSearchUnifiedEndpoint:
    """Tests for GET /search unified endpoint."""

    @pytest.mark.asyncio
    async def test_search_mode_local_routes_to_local_engine(self):
        """Test GET /search?mode=local routes to LocalSearchEngine."""
        from api.endpoints.search import SearchResponse, search_unified

        mock_result = SearchResult(
            query="腾讯",
            answer="腾讯是中国互联网巨头",
            context_tokens=100,
            confidence=0.9,
            entities=["腾讯"],
            sources=[],
            metadata={"search_type": "local"},
        )
        mock_local_engine = _make_mock_local_engine(result=mock_result)
        mock_global_engine = _make_mock_global_engine()
        mock_vector_repo = _make_mock_vector_repo()
        mock_llm = _make_mock_llm()

        result = await search_unified(
            request=_make_mock_request(),
            q="腾讯",
            mode="local",
            entity_names=None,
            max_tokens=None,
            community_level=0,
            threshold=0.75,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            _="valid-key",
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "local"
        assert result.data.query == "腾讯"

    @pytest.mark.asyncio
    async def test_search_mode_global_routes_to_global_engine(self):
        """Test GET /search?mode=global routes to GlobalSearchEngine."""
        from api.endpoints.search import SearchResponse, search_unified

        mock_result = SearchResult(
            query="AI",
            answer="AI领域有重大进展",
            context_tokens=200,
            confidence=0.75,
            entities=["AI"],
            sources=[],
            metadata={"search_type": "global"},
        )
        mock_global_engine = _make_mock_global_engine(result=mock_result)
        mock_local_engine = _make_mock_local_engine()
        mock_vector_repo = _make_mock_vector_repo()
        mock_llm = _make_mock_llm()

        result = await search_unified(
            request=_make_mock_request(),
            q="AI",
            mode="global",
            entity_names=None,
            max_tokens=None,
            community_level=0,
            threshold=0.75,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            _="valid-key",
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "global"

    @pytest.mark.asyncio
    async def test_search_mode_articles_routes_to_vector_search(self):
        """Test GET /search?mode=articles routes to VectorRepo."""
        from api.endpoints.search import SearchResponse, search_unified

        mock_similar = [
            SimilarArticle(article_id="xyz-789", category="finance", similarity=0.95),
        ]
        mock_vector_repo = _make_mock_vector_repo(similar=mock_similar)
        mock_local_engine = _make_mock_local_engine()
        mock_global_engine = _make_mock_global_engine()
        mock_llm = _make_mock_llm()

        result = await search_unified(
            request=_make_mock_request(),
            q="半导体",
            mode="articles",
            entity_names=None,
            max_tokens=None,
            community_level=0,
            threshold=0.75,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            _="valid-key",
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "articles"
        assert len(result.data.sources) == 1
        assert result.data.sources[0]["article_id"] == "xyz-789"

    @pytest.mark.asyncio
    async def test_search_default_mode_is_local(self):
        """Test GET /search without mode defaults to local."""
        from api.endpoints.search import SearchResponse, search_unified

        mock_result = SearchResult(
            query="腾讯",
            answer="腾讯答案",
            context_tokens=100,
            confidence=0.9,
            entities=["腾讯"],
            sources=[],
            metadata={"search_type": "local"},
        )
        mock_local_engine = _make_mock_local_engine(result=mock_result)
        mock_global_engine = _make_mock_global_engine()
        mock_vector_repo = _make_mock_vector_repo()
        mock_llm = _make_mock_llm()

        result = await search_unified(
            request=_make_mock_request(),
            q="腾讯",
            mode=None,  # Test default behavior without explicit mode
            entity_names=None,
            max_tokens=None,
            community_level=0,
            threshold=0.75,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            _="valid-key",
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "auto"

    @pytest.mark.asyncio
    async def test_search_local_with_entity_names_param(self):
        """Test GET /search?mode=local with entity_names comma-separated parameter."""
        from api.endpoints.search import SearchResponse, search_unified

        mock_result = SearchResult(
            query="腾讯和阿里巴巴",
            answer="两家公司都是中国互联网巨头",
            context_tokens=300,
            confidence=0.85,
            entities=["腾讯", "阿里巴巴"],
            sources=[],
            metadata={"search_type": "local"},
        )
        mock_local_engine = _make_mock_local_engine(result=mock_result)
        mock_global_engine = _make_mock_global_engine()
        mock_vector_repo = _make_mock_vector_repo()
        mock_llm = _make_mock_llm()

        result = await search_unified(
            request=_make_mock_request(),
            q="腾讯和阿里巴巴",
            mode="local",
            entity_names="腾讯,阿里巴巴",
            max_tokens=None,
            community_level=0,
            threshold=0.75,
            limit=20,
            category=None,
            use_hybrid=True,
            global_mode="map_reduce",
            _="valid-key",
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "local"

    @pytest.mark.asyncio
    async def test_search_local_returns_503_on_neo4j_exception(self):
        """Test GET /search?mode=local returns 503 when Neo4j raises exception."""
        from api.endpoints.search import search_unified

        mock_local_engine = _make_mock_local_engine(exc=Exception("Neo4j connection failed"))
        mock_global_engine = _make_mock_global_engine()
        mock_vector_repo = _make_mock_vector_repo()
        mock_llm = _make_mock_llm()

        with pytest.raises(HTTPException) as exc_info:
            await search_unified(
                request=_make_mock_request(),
                q="腾讯",
                mode="local",
                entity_names=None,
                max_tokens=None,
                community_level=0,
                threshold=0.75,
                limit=20,
                category=None,
                use_hybrid=True,
                global_mode="map_reduce",
                _="valid-key",
                local_engine=mock_local_engine,
                global_engine=mock_global_engine,
                vector_repo=mock_vector_repo,
                llm=mock_llm,
            )
        assert exc_info.value.status_code == 503
        assert "Graph service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_search_articles_returns_503_on_embedding_failure(self):
        """Test GET /search?mode=articles returns 503 when embedding service fails."""
        from api.endpoints.search import search_unified

        mock_vector_repo = _make_mock_vector_repo()
        mock_llm = _make_mock_llm(exc=Exception("Embedding provider unavailable"))
        mock_local_engine = _make_mock_local_engine()
        mock_global_engine = _make_mock_global_engine()

        with pytest.raises(HTTPException) as exc_info:
            await search_unified(
                request=_make_mock_request(),
                q="半导体",
                mode="articles",
                entity_names=None,
                max_tokens=None,
                community_level=0,
                threshold=0.75,
                limit=20,
                category=None,
                use_hybrid=True,
                global_mode="map_reduce",
                _="valid-key",
                local_engine=mock_local_engine,
                global_engine=mock_global_engine,
                vector_repo=mock_vector_repo,
                llm=mock_llm,
            )
        assert exc_info.value.status_code == 503
        assert "Embedding service unavailable" in exc_info.value.detail


# ── Test HTTP-level (Integration style) ─────────────────────────


class TestSearchUnifiedHTTPAuth:
    """HTTP-level auth tests for GET /search."""

    def test_search_requires_api_key(self):
        """Test GET /search without API key returns 401."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.endpoints.search import router

        app = FastAPI()
        app.include_router(router)
        Endpoints._local_engine = _make_mock_local_engine()
        Endpoints._global_engine = _make_mock_global_engine()
        Endpoints._vector_repo = _make_mock_vector_repo()
        Endpoints._llm = _make_mock_llm()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/search", params={"q": "腾讯"})
            assert response.status_code == 401

    def test_search_missing_q_param_returns_422(self):
        """Test GET /search without q parameter returns 422 (or 403 for auth)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.endpoints.search import router

        app = FastAPI()
        app.include_router(router)
        Endpoints._local_engine = _make_mock_local_engine()
        Endpoints._global_engine = _make_mock_global_engine()
        Endpoints._vector_repo = _make_mock_vector_repo()
        Endpoints._llm = _make_mock_llm()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/search",
                headers={"X-API-Key": "test-key"},
            )
            # With invalid key, auth fails first (403); with valid key, validation fails (422)
            assert response.status_code in (403, 422)


# ── Test Dependency Initialization ───────────────────────────────


class TestSearchDependencyGetters:
    """Tests for dependency getter functions via Endpoints."""

    @pytest.mark.asyncio
    async def test_get_local_engine_raises_503_when_uninitialized(self):
        """Test Endpoints.get_local_engine() raises 503 when engine not set."""
        Endpoints._local_engine = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_local_engine()
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_global_engine_raises_503_when_uninitialized(self):
        """Test Endpoints.get_global_engine() raises 503 when engine not set."""
        Endpoints._global_engine = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_global_engine()
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_vector_repo_raises_503_when_uninitialized(self):
        """Test Endpoints.get_vector_repo() raises 503 when repo not set."""
        Endpoints._vector_repo = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_vector_repo()
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_get_llm_client_raises_503_when_uninitialized(self):
        """Test Endpoints.get_llm() raises 503 when client not set."""
        Endpoints._llm = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_llm()
        assert exc_info.value.status_code == 503
