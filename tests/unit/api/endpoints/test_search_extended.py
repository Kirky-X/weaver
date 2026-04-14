# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Extended unit tests for search API endpoints.

Covers:
- DRIFT search endpoint (lines 254-300)
- Causal search endpoint (lines 375-445)
- Temporal search endpoint (lines 472-507)
- Error handling and degradation scenarios

Target: 85%+ coverage for src/api/endpoints/content/search.py
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from tests.helpers import (
    AsyncContextManagerMock,
    create_mock_postgres_session,
    generate_random_string,
)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock FastAPI Request object."""
    request = MagicMock(spec=Request)
    request.client.host = "127.0.0.1"
    return request


@pytest.fixture
def mock_local_engine() -> MagicMock:
    """Create a mock LocalSearchEngine."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "Local search answer",
            "context_tokens": 500,
            "confidence": 0.85,
            "entities": ["Entity A", "Entity B"],
            "sources": [{"id": "src1", "title": "Source 1"}],
            "metadata": {"search_type": "local"},
        }
    )
    return engine


@pytest.fixture
def mock_global_engine() -> MagicMock:
    """Create a mock GlobalSearchEngine."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "Global search answer",
            "context_tokens": 1000,
            "confidence": 0.90,
            "entities": ["Entity C", "Entity D"],
            "sources": [{"id": "src2", "title": "Source 2"}],
            "metadata": {"search_type": "global"},
        }
    )
    engine._context_builder = MagicMock()
    engine._llm = MagicMock()
    return engine


@pytest.fixture
def mock_vector_repo() -> MagicMock:
    """Create a mock VectorRepo."""
    repo = MagicMock()
    repo.search = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLMClient."""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value={"content": "LLM response"})
    return llm


@pytest.fixture
def mock_hybrid_engine() -> MagicMock:
    """Create a mock HybridSearchEngine."""
    engine = MagicMock()
    engine.search = AsyncMock(
        return_value={
            "answer": "Hybrid search answer",
            "context_tokens": 750,
            "confidence": 0.88,
            "entities": ["Entity E"],
            "sources": [{"id": "src3", "title": "Source 3"}],
            "metadata": {"search_type": "hybrid"},
        }
    )
    return engine


@pytest.fixture
def mock_graph_pool() -> MagicMock:
    """Create a mock GraphPool."""
    pool = MagicMock()
    pool.session = MagicMock(return_value=AsyncContextManagerMock())
    return pool


@pytest.fixture
def api_key() -> str:
    """Return a valid API key."""
    return "test-api-key-123"


# ── DRIFT Search Tests (Lines 254-300) ──────────────────────────────


class TestDriftSearchEndpoint:
    """Tests for DRIFT search endpoint."""

    @pytest.mark.asyncio
    async def test_drift_search_success(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Test successful DRIFT search with default parameters."""
        from api.endpoints.content.search import (
            DriftSearchRequest,
            DriftSearchResponse,
            search_drift,
        )

        # Mock DRIFT engine
        mock_drift_result = MagicMock()
        mock_drift_result.query = "test query"
        mock_drift_result.answer = "DRIFT search answer"
        mock_drift_result.confidence = 0.85
        mock_drift_result.hierarchy = MagicMock()
        mock_drift_result.hierarchy.primer = {"answer": "primer answer"}
        mock_drift_result.hierarchy.follow_ups = [
            {"question": "Q1", "answer": "A1"},
        ]
        mock_drift_result.primer_communities = 3
        mock_drift_result.follow_up_iterations = 2
        mock_drift_result.total_llm_calls = 5
        mock_drift_result.drift_mode = "auto"
        mock_drift_result.metadata = {"total_time_ms": 1500}

        mock_drift_engine = MagicMock()
        mock_drift_engine.search = AsyncMock(return_value=mock_drift_result)

        with patch(
            "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
            return_value=mock_drift_engine,
        ):
            body = DriftSearchRequest(
                query="What is the relationship between X and Y?",
                primer_k=3,
                max_follow_ups=2,
                confidence_threshold=0.7,
            )

            result = await search_drift(
                request=mock_request,
                body=body,
                _=api_key,
                local_engine=mock_local_engine,
                global_engine=mock_global_engine,
            )

            assert result.data.query == "test query"
            assert result.data.answer == "DRIFT search answer"
            assert result.data.confidence == 0.85
            assert result.data.search_type == "drift"
            assert "primer" in result.data.hierarchy
            assert "follow_ups" in result.data.hierarchy
            assert result.data.primer_communities == 3
            assert result.data.drift_mode == "auto"

    @pytest.mark.asyncio
    async def test_drift_search_custom_parameters(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Test DRIFT search with custom parameters."""
        from api.endpoints.content.search import DriftSearchRequest, search_drift

        mock_drift_result = MagicMock()
        mock_drift_result.query = "custom query"
        mock_drift_result.answer = "Custom DRIFT answer"
        mock_drift_result.confidence = 0.92
        mock_drift_result.hierarchy = MagicMock()
        mock_drift_result.hierarchy.primer = {}
        mock_drift_result.hierarchy.follow_ups = []
        mock_drift_result.primer_communities = 5
        mock_drift_result.follow_up_iterations = 3
        mock_drift_result.total_llm_calls = 8
        mock_drift_result.drift_mode = "deep"
        mock_drift_result.metadata = {}

        mock_drift_engine = MagicMock()
        mock_drift_engine.search = AsyncMock(return_value=mock_drift_result)

        with patch(
            "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
            return_value=mock_drift_engine,
        ):
            body = DriftSearchRequest(
                query="custom query",
                primer_k=5,
                max_follow_ups=3,
                confidence_threshold=0.85,
            )

            result = await search_drift(
                request=mock_request,
                body=body,
                _=api_key,
                local_engine=mock_local_engine,
                global_engine=mock_global_engine,
            )

            assert result.data.confidence == 0.92
            assert result.data.primer_communities == 5
            assert result.data.total_llm_calls == 8

    @pytest.mark.asyncio
    async def test_drift_search_graph_service_error(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Test DRIFT search when graph service is unavailable."""
        from api.endpoints.content.search import DriftSearchRequest, search_drift

        with patch(
            "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
            side_effect=Exception("Neo4j connection failed"),
        ):
            body = DriftSearchRequest(query="test query")

            with pytest.raises(HTTPException) as exc_info:
                await search_drift(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    local_engine=mock_local_engine,
                    global_engine=mock_global_engine,
                )

            assert exc_info.value.status_code == 503
            assert "Graph service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_drift_search_llm_error(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Test DRIFT search when LLM service is unavailable."""
        from api.endpoints.content.search import DriftSearchRequest, search_drift

        with patch(
            "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
            side_effect=Exception("LLM API timeout"),
        ):
            body = DriftSearchRequest(query="test query")

            with pytest.raises(HTTPException) as exc_info:
                await search_drift(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    local_engine=mock_local_engine,
                    global_engine=mock_global_engine,
                )

            assert exc_info.value.status_code == 503
            assert "LLM service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_drift_search_generic_error(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """Test DRIFT search with generic error."""
        from api.endpoints.content.search import DriftSearchRequest, search_drift

        with patch(
            "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
            side_effect=Exception("Unexpected error"),
        ):
            body = DriftSearchRequest(query="test query")

            with pytest.raises(HTTPException) as exc_info:
                await search_drift(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    local_engine=mock_local_engine,
                    global_engine=mock_global_engine,
                )

            assert exc_info.value.status_code == 500
            assert "DRIFT search failed" in exc_info.value.detail


# ── Causal Search Tests (Lines 375-445) ─────────────────────────────


class TestCausalSearchEndpoint:
    """Tests for causal search endpoint."""

    @pytest.mark.asyncio
    async def test_causal_search_success(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test successful causal search."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        mock_results = [
            {"id": "1", "content": "Event A caused Event B", "score": 0.9},
            {"id": "2", "content": "Event B led to Event C", "score": 0.85},
        ]

        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=mock_results)

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
        ):
            with patch(
                "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                return_value=mock_graph_pool,
            ):
                body = CausalSearchRequest(
                    query="Why did the market crash?",
                    max_depth=3,
                    min_confidence=0.7,
                )

                result = await search_causal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                )

                assert result.data.query == "Why did the market crash?"
                assert len(result.data.causal_chain) == 2
                assert result.data.causal_chain[0]["id"] == "1"
                assert result.data.causal_chain[1]["content"] == "Event B led to Event C"
                assert result.data.confidence == pytest.approx(0.875, rel=1e-2)
                assert result.data.metadata["depth"] == 3

    @pytest.mark.asyncio
    async def test_causal_search_empty_results(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test causal search with no results."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=[])

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
        ):
            with patch(
                "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                return_value=mock_graph_pool,
            ):
                body = CausalSearchRequest(
                    query="Why did nothing happen?",
                    max_depth=2,
                    min_confidence=0.9,
                )

                result = await search_causal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                )

                assert len(result.data.causal_chain) == 0
                assert result.data.confidence == 0.0
                assert "Found 0 related events" in result.data.answer

    @pytest.mark.asyncio
    async def test_causal_search_graph_service_error(
        self,
        mock_request: MagicMock,
        api_key: str,
    ) -> None:
        """Test causal search when graph service is unavailable."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        with patch(
            "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
            side_effect=Exception("Neo4j connection refused"),
        ):
            body = CausalSearchRequest(query="Why did X happen?")

            with pytest.raises(HTTPException) as exc_info:
                await search_causal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                )

            assert exc_info.value.status_code == 503
            assert "Graph service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_causal_search_generic_error(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test causal search with generic error."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            side_effect=Exception("Internal error"),
        ):
            with patch(
                "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                return_value=mock_graph_pool,
            ):
                body = CausalSearchRequest(query="test query")

                with pytest.raises(HTTPException) as exc_info:
                    await search_causal(
                        request=mock_request,
                        body=body,
                        _=api_key,
                    )

                assert exc_info.value.status_code == 500
                assert "Causal search failed" in exc_info.value.detail


# ── Temporal Search Tests (Lines 472-507) ───────────────────────────


class TestTemporalSearchEndpoint:
    """Tests for temporal search endpoint."""

    @pytest.mark.asyncio
    async def test_temporal_search_success(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test successful temporal search."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_events = [
            {"id": "1", "timestamp": "2024-01-01T00:00:00Z", "content": "Event A"},
            {"id": "2", "timestamp": "2024-01-05T00:00:00Z", "content": "Event B"},
            {"id": "3", "timestamp": "2024-01-10T00:00:00Z", "content": "Event C"},
        ]

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.get_temporal_chain = AsyncMock(return_value=mock_events)

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            with patch(
                "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                return_value=mock_graph_pool,
            ):
                body = TemporalSearchRequest(
                    query="What happened in January 2024?",
                    time_window_days=30,
                    limit=10,
                )

                result = await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                )

                assert result.data.query == "What happened in January 2024?"
                assert len(result.data.events) == 3
                assert result.data.time_range["start"] == "2024-01-01T00:00:00Z"
                assert result.data.time_range["end"] == "2024-01-10T00:00:00Z"
                assert result.data.time_range["window_days"] == 30
                assert result.data.metadata["limit"] == 10

    @pytest.mark.asyncio
    async def test_temporal_search_empty_events(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test temporal search with no events."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.get_temporal_chain = AsyncMock(return_value=[])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            with patch(
                "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                return_value=mock_graph_pool,
            ):
                body = TemporalSearchRequest(
                    query="What happened?",
                    time_window_days=7,
                    limit=5,
                )

                result = await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                )

                assert len(result.data.events) == 0
                assert result.data.time_range["start"] is None
                assert result.data.time_range["end"] is None
                assert result.data.time_range["window_days"] == 7

    @pytest.mark.asyncio
    async def test_temporal_search_partial_timestamps(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test temporal search with events missing timestamps."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_events = [
            {"id": "1", "timestamp": "2024-01-01T00:00:00Z", "content": "Event A"},
            {"id": "2", "content": "Event B (no timestamp)"},
            {"id": "3", "timestamp": "2024-01-10T00:00:00Z", "content": "Event C"},
        ]

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.get_temporal_chain = AsyncMock(return_value=mock_events)

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            with patch(
                "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                return_value=mock_graph_pool,
            ):
                body = TemporalSearchRequest(
                    query="Timeline query",
                    time_window_days=14,
                    limit=10,
                )

                result = await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                )

                assert len(result.data.events) == 3
                assert result.data.time_range["start"] == "2024-01-01T00:00:00Z"
                assert result.data.time_range["end"] == "2024-01-10T00:00:00Z"

    @pytest.mark.asyncio
    async def test_temporal_search_graph_service_error(
        self,
        mock_request: MagicMock,
        api_key: str,
    ) -> None:
        """Test temporal search when graph service is unavailable."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        with patch(
            "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
            side_effect=Exception("Neo4j connection timeout"),
        ):
            body = TemporalSearchRequest(query="When did X happen?")

            with pytest.raises(HTTPException) as exc_info:
                await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                )

            assert exc_info.value.status_code == 503
            assert "Graph service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_temporal_search_generic_error(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test temporal search with generic error."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            side_effect=Exception("Database error"),
        ):
            with patch(
                "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                return_value=mock_graph_pool,
            ):
                body = TemporalSearchRequest(query="test query")

                with pytest.raises(HTTPException) as exc_info:
                    await search_temporal(
                        request=mock_request,
                        body=body,
                        _=api_key,
                    )

                assert exc_info.value.status_code == 500
                assert "Temporal search failed" in exc_info.value.detail


# ── Parameterized Error Handling Tests ───────────────────────────────


class TestErrorHandling:
    """Parameterized tests for error handling across all endpoints."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "endpoint_class,request_class,error_message,expected_status,expected_detail",
        [
            (
                "drift",
                "DriftSearchRequest",
                "Neo4j connection failed",
                503,
                "Graph service unavailable",
            ),
            (
                "drift",
                "DriftSearchRequest",
                "LLM timeout",
                503,
                "LLM service unavailable",
            ),
            (
                "drift",
                "DriftSearchRequest",
                "Random error",
                500,
                "DRIFT search failed",
            ),
            (
                "causal",
                "CausalSearchRequest",
                "Neo4j refused",
                503,
                "Graph service unavailable",
            ),
            (
                "causal",
                "CausalSearchRequest",
                "Internal error",
                500,
                "Causal search failed",
            ),
            (
                "temporal",
                "TemporalSearchRequest",
                "Neo4j timeout",
                503,
                "Graph service unavailable",
            ),
            (
                "temporal",
                "TemporalSearchRequest",
                "DB error",
                500,
                "Temporal search failed",
            ),
        ],
    )
    async def test_error_handling_patterns(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
        endpoint_class: str,
        request_class: str,
        error_message: str,
        expected_status: int,
        expected_detail: str,
    ) -> None:
        """Test error handling patterns for all search endpoints."""
        from api.endpoints.content.search import (
            CausalSearchRequest,
            DriftSearchRequest,
            TemporalSearchRequest,
            search_causal,
            search_drift,
            search_temporal,
        )

        if endpoint_class == "drift":
            request_body = DriftSearchRequest(query="test")
            with patch(
                "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
                side_effect=Exception(error_message),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await search_drift(
                        request=mock_request,
                        body=request_body,
                        _=api_key,
                        local_engine=mock_local_engine,
                        global_engine=mock_global_engine,
                    )
        elif endpoint_class == "causal":
            request_body = CausalSearchRequest(query="test")
            with patch(
                "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
                side_effect=Exception(error_message),
            ):
                with patch(
                    "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                    return_value=mock_graph_pool,
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await search_causal(
                            request=mock_request,
                            body=request_body,
                            _=api_key,
                        )
        else:  # temporal
            request_body = TemporalSearchRequest(query="test")
            with patch(
                "modules.memory.graphs.temporal.TemporalGraphRepo",
                side_effect=Exception(error_message),
            ):
                with patch(
                    "api.endpoints.content.search.deps.Endpoints.get_graph_pool",
                    return_value=mock_graph_pool,
                ):
                    with pytest.raises(HTTPException) as exc_info:
                        await search_temporal(
                            request=mock_request,
                            body=request_body,
                            _=api_key,
                        )

        assert exc_info.value.status_code == expected_status
        assert expected_detail in exc_info.value.detail
