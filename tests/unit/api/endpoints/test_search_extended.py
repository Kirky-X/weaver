# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
        """Test successful causal search.

        D5 changes: search_causal now reads ``engine.last_metadata`` to pick
        the answer text branch and apply the degraded confidence cap. The
        mock MUST expose a real dict (MagicMock auto-returns truthy values,
        which would wrongly trigger the degraded cap).
        """
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        mock_results = [
            {"id": "1", "content": "Event A caused Event B", "score": 0.9},
            {"id": "2", "content": "Event B led to Event C", "score": 0.85},
        ]

        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=mock_results)
        # D5: provide real metadata dict (causal_edges_traversed>0 → "found
        # causal chain" answer; degraded=False → no confidence cap).
        mock_adaptive_engine.last_metadata = {
            "causal_edges_traversed": 2,
            "degraded": False,
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
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
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )

            assert result.data.query == "Why did the market crash?"
            assert len(result.data.causal_chain) == 2
            assert result.data.causal_chain[0].id == "1"
            assert result.data.causal_chain[1].content == "Event B led to Event C"
            assert result.data.confidence == pytest.approx(0.875, rel=1e-2)
            assert result.data.metadata["depth"] == 3
            # D5 / Task 5.6: metadata exposes causal_edges_traversed + degraded
            assert result.data.metadata["causal_edges_traversed"] == 2
            assert result.data.metadata["degraded"] is False
            # answer 文本应反映"找到因果链"分支
            assert "因果链" in result.data.answer

    @pytest.mark.asyncio
    async def test_causal_search_empty_results(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test causal search with no results.

        D5: empty results → answer="未找到与查询相关的事件", confidence=0.0.
        Metadata must be set explicitly so MagicMock auto-truthy doesn't
        leak into the degraded cap branch.
        """
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=[])
        # D5: explicit metadata (no anchors → no edges traversed, not degraded)
        mock_adaptive_engine.last_metadata = {
            "causal_edges_traversed": 0,
            "degraded": False,
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
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
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )

            assert len(result.data.causal_chain) == 0
            assert result.data.confidence == 0.0
            assert "相关" in result.data.answer or "causal events" in result.data.answer

    @pytest.mark.asyncio
    async def test_causal_answer_text_no_causal_edges(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """D5 / Task 5.3: 无 CAUSES 边时 answer 文本应反映"未找到因果链"。

        场景：图 DB 中 0 条 CAUSES 边（Q1 finding），但 anchor 搜索返回了
        语义相关事件。旧行为：谎称"找到 N 个相关事件的因果链"。
        新行为：明确告知"未找到与查询相关的因果链，返回 N 个语义相关事件"，
        confidence 为结果 score 均值（不受 0.3 上限，因 degraded=False）。
        """
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        mock_results = [
            {"id": "1", "content": "semantic event A", "score": 0.6},
            {"id": "2", "content": "semantic event B", "score": 0.4},
        ]
        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=mock_results)
        # Q1 场景：有 anchor 但 0 条 CAUSES 边
        mock_adaptive_engine.last_metadata = {
            "causal_edges_traversed": 0,
            "degraded": False,
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
        ):
            body = CausalSearchRequest(query="IT之家", max_depth=2, min_confidence=0.0)

            result = await search_causal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )

            # 核心：answer 文本不再谎称找到因果链
            assert "未找到与查询相关的因果链" in result.data.answer
            assert "语义相关事件" in result.data.answer
            assert "2" in result.data.answer  # 包含结果数
            # confidence 为 score 均值（0.6+0.4)/2=0.5，未触发退化上限
            assert result.data.confidence == pytest.approx(0.5, rel=1e-2)
            # metadata 暴露真实状态
            assert result.data.metadata["causal_edges_traversed"] == 0
            assert result.data.metadata["degraded"] is False

    @pytest.mark.asyncio
    async def test_causal_confidence_capped_when_degraded(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """D3 / Task 5.5: 退化场景 confidence 上限 0.3。

        场景：beam search 返回 3 个 score 全为 1.0 的结果（旧行为归一化为
        1.0 谎称完美匹配）。新行为：
        - AdaptiveSearchEngine 归一化把所有 score 设为 0.0 + degraded=True
        - 端点 confidence = min(avg(0.0,0.0,0.0), 0.3) = min(0.0, 0.3) = 0.0
        但即使 score 没被设为 0.0（外部直接构造的场景），degraded=True 仍
        触发 0.3 上限，防止"全 1.0 score → confidence=1.0 谎言"。
        """
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        # 模拟旧行为：3 个 score 全为 1.0（未经 D3 归一化修复的场景）
        # 这种情况下端点应仍受 0.3 上限保护
        mock_results = [
            {"id": "1", "content": "identical score event A", "score": 1.0},
            {"id": "2", "content": "identical score event B", "score": 1.0},
            {"id": "3", "content": "identical score event C", "score": 1.0},
        ]
        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=mock_results)
        # D3 退化场景：score_range==0 + >=2 results
        mock_adaptive_engine.last_metadata = {
            "causal_edges_traversed": 0,
            "degraded": True,
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
        ):
            body = CausalSearchRequest(query="IT之家", max_depth=2, min_confidence=0.0)

            result = await search_causal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )

            # 核心：confidence 受 0.3 上限约束（旧行为会返回 1.0）
            assert result.data.confidence <= 0.3
            # 由于 causal_edges_traversed=0，answer 应为"未找到因果链"分支
            assert "未找到与查询相关的因果链" in result.data.answer
            # metadata 暴露 degraded 状态
            assert result.data.metadata["degraded"] is True
            assert result.data.metadata["causal_edges_traversed"] == 0

    @pytest.mark.asyncio
    async def test_causal_search_graph_service_error(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test causal search when graph service is unavailable."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            side_effect=Exception("Neo4j connection refused"),
        ):
            body = CausalSearchRequest(query="Why did X happen?")

            with pytest.raises(HTTPException) as exc_info:
                await search_causal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    graph_pool=mock_graph_pool,
                    embedding_service=None,
                    intent_classifier=None,
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
            body = CausalSearchRequest(query="test query")

            with pytest.raises(HTTPException) as exc_info:
                await search_causal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    graph_pool=mock_graph_pool,
                    embedding_service=MagicMock(),
                    intent_classifier=MagicMock(),
                )

            assert exc_info.value.status_code == 500
            assert "Internal server error during causal search" in exc_info.value.detail


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
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=mock_events)

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(
                query="What happened in January 2024?",
                time_range="30d",
                limit=10,
            )

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            assert result.data.query == "What happened in January 2024?"
            assert len(result.data.events) == 3
            # time_range 现在是请求窗口（int 秒），不是事件 min/max
            assert isinstance(result.data.time_range["start"], int)
            assert isinstance(result.data.time_range["end"], int)
            assert result.data.time_range["window_days"] == 30.0
            # 验证 search_temporal_events 被调用且传了时间参数
            mock_temporal_repo.search_temporal_events.assert_called_once()
            call_kwargs = mock_temporal_repo.search_temporal_events.call_args.kwargs
            assert call_kwargs["query"] == "What happened in January 2024?"
            assert call_kwargs["limit"] == 10
            assert "start_time" in call_kwargs
            assert "end_time" in call_kwargs
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
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=[])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(
                query="What happened?",
                time_range="7d",
                limit=5,
            )

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            assert len(result.data.events) == 0
            # 空结果时 time_range 仍为请求窗口（int 秒），不是 None
            assert isinstance(result.data.time_range["start"], int)
            assert isinstance(result.data.time_range["end"], int)
            assert result.data.time_range["window_days"] == 7.0

    @pytest.mark.asyncio
    async def test_temporal_search_partial_timestamps(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test temporal search with events missing timestamps — dirty events filtered out."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_events = [
            {"id": "1", "timestamp": "2024-01-01T00:00:00Z", "content": "Event A"},
            {"id": "2", "content": "Event B (no timestamp)"},
            {"id": "3", "timestamp": "2024-01-10T00:00:00Z", "content": "Event C"},
        ]

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=mock_events)

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(
                query="Timeline query",
                time_range="14d",
                limit=10,
            )

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            # 没 timestamp 的事件被强制过滤（脏数据防御）
            assert len(result.data.events) == 2
            assert all(e.get("timestamp") for e in result.data.events)
            # time_range 是请求窗口（int 秒）
            assert isinstance(result.data.time_range["start"], int)
            assert isinstance(result.data.time_range["end"], int)
            assert result.data.time_range["window_days"] == 14.0

    @pytest.mark.asyncio
    async def test_temporal_search_graph_service_error(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Test temporal search when graph service is unavailable."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            side_effect=Exception("Neo4j connection timeout"),
        ):
            body = TemporalSearchRequest(query="When did X happen?")

            with pytest.raises(HTTPException) as exc_info:
                await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    graph_pool=mock_graph_pool,
                    embedding_service=None,
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
            body = TemporalSearchRequest(query="test query")

            with pytest.raises(HTTPException) as exc_info:
                await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    graph_pool=mock_graph_pool,
                    embedding_service=None,
                )

            assert exc_info.value.status_code == 500
            assert "Internal server error during temporal search" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_temporal_search_filters_by_time_window(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Verify search_temporal_events receives correct start_time/end_time from time_range."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=[])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="test", time_range="7d", limit=10)

            await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            call_kwargs = mock_temporal_repo.search_temporal_events.call_args.kwargs
            assert "start_time" in call_kwargs
            assert "end_time" in call_kwargs
            # 7d = 604800 秒
            assert call_kwargs["end_time"] - call_kwargs["start_time"] == 604800

    @pytest.mark.asyncio
    async def test_temporal_search_excludes_zero_timestamp(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Legacy dirty data (timestamp=0 from writer bug) must be excluded from response."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_events = [
            {"id": "1", "timestamp": 0, "content": "Dirty event (legacy bug)"},
            {"id": "2", "timestamp": 1782400000, "content": "Valid event"},
            {"id": "3", "timestamp": 0, "content": "Another dirty event"},
        ]

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=mock_events)

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="test", time_range="7d")

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            # timestamp=0 的事件被过滤，只保留 1 个有效事件
            assert len(result.data.events) == 1
            assert result.data.events[0]["id"] == "2"
            assert result.data.events[0]["timestamp"] == 1782400000

    @pytest.mark.asyncio
    async def test_temporal_search_invalid_time_range_format(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Invalid time_range format returns HTTP 400."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="test", time_range="invalid")

            with pytest.raises(HTTPException) as exc_info:
                await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    graph_pool=mock_graph_pool,
                    embedding_service=None,
                )

            assert exc_info.value.status_code == 400
            assert "Invalid time_range format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_temporal_search_hours_format(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """time_range='24h' parses to 86400 seconds window (1 day)."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=[])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="test", time_range="24h")

            await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            call_kwargs = mock_temporal_repo.search_temporal_events.call_args.kwargs
            # 24h = 86400 秒
            assert call_kwargs["end_time"] - call_kwargs["start_time"] == 86400

    @pytest.mark.asyncio
    async def test_temporal_search_minutes_format(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """time_range='30m' parses to 1800 seconds window."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=[])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="test", time_range="30m")

            await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            call_kwargs = mock_temporal_repo.search_temporal_events.call_args.kwargs
            # 30m = 1800 秒
            assert call_kwargs["end_time"] - call_kwargs["start_time"] == 1800

    @pytest.mark.asyncio
    async def test_temporal_search_empty_window(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Empty result still returns request window in time_range.start/end."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=[])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="test", time_range="7d")

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            # 空结果时 time_range 仍为请求窗口
            assert len(result.data.events) == 0
            start = result.data.time_range["start"]
            end = result.data.time_range["end"]
            assert isinstance(start, int)
            assert isinstance(end, int)
            assert end - start == 604800  # 7d
            assert result.data.time_range["window_days"] == 7.0


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
                "Internal server error during causal search",
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
                "Internal server error during temporal search",
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
            mock_embedding = MagicMock()
            mock_intent = MagicMock()
            with patch(
                "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
                side_effect=Exception(error_message),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await search_causal(
                        request=mock_request,
                        body=request_body,
                        _=api_key,
                        graph_pool=mock_graph_pool,
                        embedding_service=mock_embedding,
                        intent_classifier=mock_intent,
                    )
        else:  # temporal
            request_body = TemporalSearchRequest(query="test")
            with patch(
                "modules.memory.graphs.temporal.TemporalGraphRepo",
                side_effect=Exception(error_message),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await search_temporal(
                        request=mock_request,
                        body=request_body,
                        _=api_key,
                        graph_pool=mock_graph_pool,
                        embedding_service=None,
                    )

        assert exc_info.value.status_code == expected_status
        assert expected_detail in exc_info.value.detail


# ── Boundary & Degradation Tests (T022-T025) ────────────────────────


class TestSearchEndpointBoundaryConditions:
    """Boundary-value and degradation tests for drift/causal/temporal endpoints.

    Covers cases not exercised by the primary test classes above:
    - DRIFT: primer_k=1 / max_follow_ups=0 boundaries
    - Causal: max_depth=1/10 / min_confidence=0.0/1.0 / degraded=True with zero scores
    - Temporal: limit=0/1 boundaries, time_range=invalid-unit returns 400
    """

    # ── DRIFT boundary tests ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_drift_primer_k_minimum_1(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """primer_k=1 is the lower bound accepted by DriftConfig."""
        from api.endpoints.content.search import DriftSearchRequest, search_drift

        mock_drift_result = MagicMock()
        mock_drift_result.query = "single primer"
        mock_drift_result.answer = "DRIFT answer with primer_k=1"
        mock_drift_result.confidence = 0.7
        mock_drift_result.hierarchy = MagicMock()
        mock_drift_result.hierarchy.primer = {"answer": "single primer answer"}
        mock_drift_result.hierarchy.follow_ups = []
        mock_drift_result.primer_communities = 1
        mock_drift_result.follow_up_iterations = 0
        mock_drift_result.total_llm_calls = 1
        mock_drift_result.drift_mode = "fast"
        mock_drift_result.metadata = {}

        mock_drift_engine = MagicMock()
        mock_drift_engine.search = AsyncMock(return_value=mock_drift_result)

        with patch(
            "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
            return_value=mock_drift_engine,
        ):
            body = DriftSearchRequest(
                query="single primer",
                primer_k=1,
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

            assert result.data.primer_communities == 1
            assert result.data.follow_up_iterations == 0

    @pytest.mark.asyncio
    async def test_drift_max_follow_ups_zero(
        self,
        mock_request: MagicMock,
        mock_local_engine: MagicMock,
        mock_global_engine: MagicMock,
        api_key: str,
    ) -> None:
        """max_follow_ups=0 means no follow-up iterations; primer-only result."""
        from api.endpoints.content.search import DriftSearchRequest, search_drift

        mock_drift_result = MagicMock()
        mock_drift_result.query = "primer only"
        mock_drift_result.answer = "DRIFT primer-only answer"
        mock_drift_result.confidence = 0.6
        mock_drift_result.hierarchy = MagicMock()
        mock_drift_result.hierarchy.primer = {"answer": "primer"}
        mock_drift_result.hierarchy.follow_ups = []
        mock_drift_result.primer_communities = 3
        mock_drift_result.follow_up_iterations = 0
        mock_drift_result.total_llm_calls = 1
        mock_drift_result.drift_mode = "fast"
        mock_drift_result.metadata = {"no_follow_ups": True}

        mock_drift_engine = MagicMock()
        mock_drift_engine.search = AsyncMock(return_value=mock_drift_result)

        with patch(
            "modules.knowledge.search.engines.drift_search.DRIFTSearchEngine",
            return_value=mock_drift_engine,
        ):
            body = DriftSearchRequest(
                query="primer only",
                primer_k=3,
                max_follow_ups=0,
                confidence_threshold=0.7,
            )

            result = await search_drift(
                request=mock_request,
                body=body,
                _=api_key,
                local_engine=mock_local_engine,
                global_engine=mock_global_engine,
            )

            assert result.data.follow_up_iterations == 0
            assert result.data.hierarchy["follow_ups"] == []

    # ── Causal boundary tests ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_causal_max_depth_minimum_1(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """max_depth=1 is the lower bound (ge=1). Single-hop causal chain only."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        mock_results = [
            {"id": "1", "content": "Direct cause", "score": 0.85},
        ]
        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=mock_results)
        mock_adaptive_engine.last_metadata = {
            "causal_edges_traversed": 1,
            "degraded": False,
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
        ):
            body = CausalSearchRequest(
                query="Why did OpenAI release GPT-5.6?",
                max_depth=1,
                min_confidence=0.5,
            )

            result = await search_causal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )

            # metadata exposes max_depth
            assert result.data.metadata["depth"] == 1
            # single-hop chain has 1 result
            assert len(result.data.causal_chain) == 1

    @pytest.mark.asyncio
    async def test_causal_min_confidence_boundary_0_and_1(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """min_confidence=0.0 (min) and =1.0 (max) accepted (ge=0.0, le=1.0)."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        # min_confidence=0.0
        mock_adaptive_engine_min = MagicMock()
        mock_adaptive_engine_min.search = AsyncMock(
            return_value=[{"id": "1", "content": "low conf", "score": 0.1}]
        )
        mock_adaptive_engine_min.last_metadata = {
            "causal_edges_traversed": 0,
            "degraded": False,
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine_min,
        ):
            body_min = CausalSearchRequest(query="Why?", max_depth=2, min_confidence=0.0)
            result_min = await search_causal(
                request=mock_request,
                body=body_min,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )
            assert len(result_min.data.causal_chain) == 1

        # min_confidence=1.0
        mock_adaptive_engine_max = MagicMock()
        mock_adaptive_engine_max.search = AsyncMock(
            return_value=[{"id": "1", "content": "high conf", "score": 1.0}]
        )
        mock_adaptive_engine_max.last_metadata = {
            "causal_edges_traversed": 1,
            "degraded": False,
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine_max,
        ):
            body_max = CausalSearchRequest(query="Why?", max_depth=2, min_confidence=1.0)
            result_max = await search_causal(
                request=mock_request,
                body=body_max,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )
            assert len(result_max.data.causal_chain) == 1

    @pytest.mark.asyncio
    async def test_causal_degraded_with_zero_scores_caps_confidence(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """degraded=True + all-zero scores → confidence=min(0.0, 0.3)=0.0.

        Combines D3 (degraded cap) + zero-score average to ensure the cap
        still binds even when average is already low.
        """
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        # 3 results, all score=0.0 → avg=0.0
        mock_results = [
            {"id": "1", "content": "zero-A", "score": 0.0},
            {"id": "2", "content": "zero-B", "score": 0.0},
            {"id": "3", "content": "zero-C", "score": 0.0},
        ]
        mock_adaptive_engine = MagicMock()
        mock_adaptive_engine.search = AsyncMock(return_value=mock_results)
        mock_adaptive_engine.last_metadata = {
            "causal_edges_traversed": 0,
            "degraded": True,  # score_range==0 with >=2 results
        }

        with patch(
            "modules.memory.retrieval.adaptive_search.AdaptiveSearchEngine",
            return_value=mock_adaptive_engine,
        ):
            body = CausalSearchRequest(query="Why?", max_depth=2, min_confidence=0.0)

            result = await search_causal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=MagicMock(),
            )

            # confidence = min(avg(0,0,0), 0.3) = min(0.0, 0.3) = 0.0
            assert result.data.confidence == 0.0
            # metadata exposes degraded state
            assert result.data.metadata["degraded"] is True
            assert result.data.metadata["causal_edges_traversed"] == 0
            # answer should be the "no causal edges" branch
            assert "未找到与查询相关的因果链" in result.data.answer

    # ── Temporal boundary tests ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_temporal_limit_zero_accepted(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """limit=0 is accepted by Pydantic (no ge constraint, default 10).

        Note: TemporalSearchRequest.limit has no ge constraint (unlike search_unified),
        so limit=0 is technically valid at the model level. The semantic is
        "return at most 0 events" — engine should return empty list.
        """
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        # limit=0 → search_temporal_events returns []
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=[])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="events", time_range="7d", limit=0)

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            assert len(result.data.events) == 0
            # limit passed through to repo
            call_kwargs = mock_temporal_repo.search_temporal_events.call_args.kwargs
            assert call_kwargs["limit"] == 0

    @pytest.mark.asyncio
    async def test_temporal_limit_one_accepted(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """limit=1 returns at most 1 event (top match)."""
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_events = [
            {"id": "1", "timestamp": "2024-01-01T00:00:00Z", "content": "single event"},
        ]
        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=mock_events)

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="events", time_range="7d", limit=1)

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,
            )

            assert len(result.data.events) == 1
            assert result.data.events[0]["id"] == "1"
            # limit=1 propagated to repo
            call_kwargs = mock_temporal_repo.search_temporal_events.call_args.kwargs
            assert call_kwargs["limit"] == 1

    @pytest.mark.asyncio
    async def test_temporal_invalid_unit_7w_returns_400(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """time_range='7w' (week unit not supported) → 400 Invalid time_range format.

        Only d/h/m units are valid (see _TIME_RANGE_RE in search.py).
        """
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="events", time_range="7w")

            with pytest.raises(HTTPException) as exc_info:
                await search_temporal(
                    request=mock_request,
                    body=body,
                    _=api_key,
                    graph_pool=mock_graph_pool,
                    embedding_service=None,
                )

            assert exc_info.value.status_code == 400
            assert "Invalid time_range format" in exc_info.value.detail
            # '7w' explicit in error message
            assert "7w" in exc_info.value.detail

    # ── Causal service-unavailable tests ──────────────────────────

    @pytest.mark.asyncio
    async def test_causal_embedding_service_unavailable_returns_503(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """embedding_service=None → 503 Embedding service unavailable (covers L503-504)."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        body = CausalSearchRequest(query="Why?", max_depth=2, min_confidence=0.5)

        with pytest.raises(HTTPException) as exc_info:
            await search_causal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=None,  # unavailable
                intent_classifier=MagicMock(),
            )

        assert exc_info.value.status_code == 503
        assert "Embedding service unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_causal_intent_classifier_unavailable_returns_503(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """intent_classifier=None → 503 Intent classifier unavailable (covers L508-509)."""
        from api.endpoints.content.search import CausalSearchRequest, search_causal

        body = CausalSearchRequest(query="Why?", max_depth=2, min_confidence=0.5)

        with pytest.raises(HTTPException) as exc_info:
            await search_causal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=MagicMock(),
                intent_classifier=None,  # unavailable
            )

        assert exc_info.value.status_code == 503
        assert "Intent classifier unavailable" in exc_info.value.detail

    # ── Temporal semantic-search tests ────────────────────────────

    @pytest.mark.asyncio
    async def test_temporal_semantic_search_with_embedding_service(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """When embedding_service.is_ready()=True, _semantic_temporal_search is used.

        Covers L679-706 of search.py — the cosine-similarity ranking path that
        is bypassed when embedding service is unavailable.
        """
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_events = [
            {
                "id": "1",
                "timestamp": 1782400000,
                "content": "华为发布新芯片",
            },
            {
                "id": "2",
                "timestamp": 1782400100,
                "content": "OpenAI 发布新模型",
            },
        ]
        mock_temporal_repo = MagicMock()
        mock_temporal_repo.get_events_by_timerange = AsyncMock(return_value=mock_events)

        mock_embedding = MagicMock()
        mock_embedding.is_ready.return_value = True
        mock_embedding.embed = AsyncMock(return_value=[0.1] * 8)
        mock_embedding.embed_batch = AsyncMock(return_value=[[0.2] * 8, [0.3] * 8])

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="华为", time_range="7d", limit=5)

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=mock_embedding,
            )

            # semantic path was used
            mock_temporal_repo.get_events_by_timerange.assert_called_once()
            assert len(result.data.events) == 2
            # similarity_score injected by _semantic_temporal_search
            for event in result.data.events:
                assert "similarity_score" in event

    @pytest.mark.asyncio
    async def test_temporal_embedding_failure_falls_back_to_substring(
        self,
        mock_request: MagicMock,
        mock_graph_pool: MagicMock,
        api_key: str,
    ) -> None:
        """Embedding batch failure → falls back to substring search (covers L753-770).

        The embedding service may raise during embed_batch (e.g. timeout). The
        endpoint MUST degrade gracefully to substring matching instead of 500.
        """
        from api.endpoints.content.search import TemporalSearchRequest, search_temporal

        mock_temporal_repo = MagicMock()
        mock_temporal_repo.search_temporal_events = AsyncMock(
            return_value=[
                {"id": "1", "timestamp": 1782400000, "content": "fallback event"},
            ]
        )

        mock_embedding = MagicMock()
        mock_embedding.is_ready.return_value = True
        mock_embedding.embed = AsyncMock(return_value=[0.1] * 8)
        # embed_batch raises → triggers fallback
        mock_embedding.embed_batch = AsyncMock(side_effect=Exception("Embedding timeout"))

        with patch(
            "modules.memory.graphs.temporal.TemporalGraphRepo",
            return_value=mock_temporal_repo,
        ):
            body = TemporalSearchRequest(query="华为", time_range="7d", limit=5)

            result = await search_temporal(
                request=mock_request,
                body=body,
                _=api_key,
                graph_pool=mock_graph_pool,
                embedding_service=mock_embedding,
            )

            # Fallback to substring search succeeded
            assert len(result.data.events) == 1
            assert result.data.events[0]["id"] == "1"
            # search_temporal_events called in fallback path
            mock_temporal_repo.search_temporal_events.assert_called_once()
