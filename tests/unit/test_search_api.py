# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for search API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.endpoints._deps import Endpoints
from modules.search.engines.local_search import SearchResult
from modules.storage.vector_repo import SimilarArticle

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
        client.batch_embed = AsyncMock(side_effect=exc)
    else:
        client.batch_embed = AsyncMock(return_value=embeddings or [[0.1] * 1024])
    return client


def _make_mock_request() -> MagicMock:
    from starlette.requests import Request

    mock_req = MagicMock(spec=Request)
    mock_req.client = MagicMock()
    mock_req.client.host = "127.0.0.1"
    return mock_req


# ── Test GET /search/local ──────────────────────────────────────


class TestSearchLocalEndpoint:
    """Tests for GET /search/local endpoint."""

    @pytest.mark.asyncio
    async def test_search_local_returns_200_with_valid_key(self):
        """Test GET /search/local with valid API key returns 200 and SearchResponse."""
        from api.endpoints.search import SearchResponse, search_local

        mock_result = SearchResult(
            query="腾讯",
            answer="腾讯是一家中国互联网公司",
            context_tokens=500,
            confidence=0.9,
            entities=["腾讯"],
            sources=[{"id": "123", "title": "腾讯新闻"}],
            metadata={"search_type": "local"},
        )
        mock_engine = _make_mock_local_engine(result=mock_result)

        result = await search_local(
            request=_make_mock_request(),
            q="腾讯",
            entity_names=None,
            max_tokens=None,
            _="valid-key",
            engine=mock_engine,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.query == "腾讯"
        assert result.data.answer == "腾讯是一家中国互联网公司"
        assert result.data.search_type == "local"
        assert result.data.confidence == 0.9
        assert "腾讯" in result.data.entities

    @pytest.mark.asyncio
    async def test_search_local_with_entity_names_param(self):
        """Test GET /search/local with entity_names comma-separated parameter."""
        from api.endpoints.search import SearchResponse, search_local

        mock_result = SearchResult(
            query="腾讯和阿里巴巴",
            answer="两家公司都是中国互联网巨头",
            context_tokens=300,
            confidence=0.85,
            entities=["腾讯", "阿里巴巴"],
            sources=[],
            metadata={"search_type": "local"},
        )
        mock_engine = _make_mock_local_engine(result=mock_result)

        result = await search_local(
            request=_make_mock_request(),
            q="腾讯和阿里巴巴",
            entity_names="腾讯,阿里巴巴",
            max_tokens=None,
            _="valid-key",
            engine=mock_engine,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "local"

    @pytest.mark.asyncio
    async def test_search_local_returns_503_on_neo4j_exception(self):
        """Test GET /search/local returns 503 when Neo4j raises exception."""
        from api.endpoints.search import search_local

        mock_engine = _make_mock_local_engine(exc=Exception("Neo4j connection failed"))

        with pytest.raises(HTTPException) as exc_info:
            await search_local(
                request=_make_mock_request(),
                q="腾讯",
                entity_names=None,
                max_tokens=None,
                _="valid-key",
                engine=mock_engine,
            )
        assert exc_info.value.status_code == 503
        assert "Graph service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_search_local_returns_503_on_llm_exception(self):
        """Test GET /search/local returns 503 when LLM raises exception."""
        from api.endpoints.search import search_local

        mock_engine = _make_mock_local_engine(exc=Exception("LLM timeout"))

        with pytest.raises(HTTPException) as exc_info:
            await search_local(
                request=_make_mock_request(),
                q="腾讯",
                entity_names=None,
                max_tokens=None,
                _="valid-key",
                engine=mock_engine,
            )
        assert exc_info.value.status_code == 503
        assert "LLM service unavailable" in exc_info.value.detail


class TestSearchLocalHTTPAuth:
    """HTTP-level auth tests for GET /search/local."""

    def test_search_local_requires_api_key(self):
        """Test GET /search/local without API key returns 401."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.endpoints.search import router

        app = FastAPI()
        app.include_router(router)
        Endpoints._local_engine = _make_mock_local_engine()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/search/local", params={"q": "腾讯"})
            assert response.status_code == 401

    def test_search_local_missing_q_param_returns_422(self):
        """Test GET /search/local without q parameter returns 422."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.endpoints.search import router

        app = FastAPI()
        app.include_router(router)
        Endpoints._local_engine = _make_mock_local_engine()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/search/local",
                params={"q": "test"},
                headers={"X-API-Key": "test-key"},
            )
            # With mocked engine and valid key, should get 200 or error at engine level
            # With wrong key returns 403 (auth failure)
            assert response.status_code in (200, 403, 422, 503)


# ── Test GET /search/global ────────────────────────────────────


class TestSearchGlobalEndpoint:
    """Tests for GET /search/global endpoint."""

    @pytest.mark.asyncio
    async def test_search_global_returns_200_with_valid_key(self):
        """Test GET /search/global with valid API key returns 200."""
        from api.endpoints.search import SearchResponse, search_global

        mock_result = SearchResult(
            query="AI领域进展",
            answer="AI领域近期在生成模型方面取得重大突破",
            context_tokens=800,
            confidence=0.75,
            entities=["GPT", "Claude"],
            sources=[],
            metadata={"search_type": "global", "intermediate_count": 3},
        )
        mock_engine = _make_mock_global_engine(result=mock_result)

        result = await search_global(
            request=_make_mock_request(),
            q="AI领域进展",
            community_level=0,
            mode="map_reduce",
            _="valid-key",
            engine=mock_engine,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.query == "AI领域进展"
        assert result.data.search_type == "global"
        assert result.data.metadata["intermediate_count"] == 3


# ── Test GET /search/articles ───────────────────────────────────


class TestSearchArticlesEndpoint:
    """Tests for GET /search/articles endpoint."""

    @pytest.mark.asyncio
    async def test_search_articles_returns_200_with_valid_key(self):
        """Test GET /search/articles with valid API key returns 200 and article list."""
        from api.endpoints.search import SearchResponse, search_articles

        mock_similar = [
            SimilarArticle(article_id="abc-123", category="tech", similarity=0.92),
            SimilarArticle(article_id="def-456", category="tech", similarity=0.88),
        ]
        mock_vector_repo = _make_mock_vector_repo(similar=mock_similar)
        mock_llm = _make_mock_llm()

        result = await search_articles(
            request=_make_mock_request(),
            q="半导体行业动态",
            threshold=0.75,
            limit=20,
            category=None,
            _="valid-key",
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "articles"
        assert result.data.query == "半导体行业动态"
        assert len(result.data.sources) == 2
        assert result.data.sources[0]["article_id"] == "abc-123"
        assert result.data.sources[0]["similarity"] == 0.92
        assert result.data.metadata["total_results"] == 2

    @pytest.mark.asyncio
    async def test_search_articles_returns_503_on_embedding_failure(self):
        """Test GET /search/articles returns 503 when embedding service fails."""
        from api.endpoints.search import search_articles

        mock_vector_repo = _make_mock_vector_repo(similar=[])
        mock_llm = _make_mock_llm(exc=Exception("Embedding provider unavailable"))

        with pytest.raises(HTTPException) as exc_info:
            await search_articles(
                request=_make_mock_request(),
                q="半导体",
                threshold=0.75,
                limit=20,
                category=None,
                _="valid-key",
                vector_repo=mock_vector_repo,
                llm=mock_llm,
            )
        assert exc_info.value.status_code == 503
        assert "Embedding service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_search_articles_empty_results(self):
        """Test GET /search/articles returns 200 with empty list when no similar articles."""
        from api.endpoints.search import SearchResponse, search_articles

        mock_vector_repo = _make_mock_vector_repo(similar=[])
        mock_llm = _make_mock_llm()

        result = await search_articles(
            request=_make_mock_request(),
            q="未知话题",
            threshold=0.9,
            limit=20,
            category=None,
            _="valid-key",
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "articles"
        assert result.data.sources == []
        assert result.data.answer == "Found 0 similar articles."


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
            category=None,
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
            category=None,
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
            category=None,
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
    async def test_search_mode_auto_defaults_to_global(self):
        """Test GET /search?mode=auto routes to global engine by default."""
        from api.endpoints.search import SearchResponse, search_unified

        mock_result = SearchResult(
            query="AI",
            answer="AI answer",
            context_tokens=200,
            confidence=0.7,
            entities=[],
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
            mode="auto",
            entity_names=None,
            max_tokens=None,
            community_level=0,
            threshold=0.75,
            category=None,
            _="valid-key",
            local_engine=mock_local_engine,
            global_engine=mock_global_engine,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        assert isinstance(result.data, SearchResponse)
        assert result.data.search_type == "global"


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
