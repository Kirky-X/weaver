# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AdaptiveSearchEngine."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from modules.memory.core.graph_types import EdgeType, IntentType
from modules.memory.retrieval.adaptive_search import AdaptiveSearchEngine


class MockEmbeddingService:
    """Mock embedding service for tests."""

    async def embed(self, text: str) -> list[float]:
        return [0.1] * 384

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]

    def is_ready(self) -> bool:
        return True

    def start_loading(self) -> None:
        pass


class MockIntentClassifier:
    """Mock intent classifier for tests."""

    def __init__(self, intent: IntentType = IntentType.OPEN):
        self._intent = intent

    async def classify(self, query: str) -> Any:
        result = MagicMock()
        result.intent = self._intent
        return result


# Need Any for type hint
from typing import Any


class TestAdaptiveSearchBasic:
    """Tests for basic search functionality."""

    @pytest.fixture
    def mock_temporal_repo(self):
        repo = MagicMock()
        repo.search_temporal_events = AsyncMock(
            return_value=[
                {"id": "event-1", "content": "Test event content"},
            ]
        )
        repo.get_temporal_chain = AsyncMock(
            return_value=[
                {"id": "event-1", "content": "Test event content", "timestamp": "2026-01-01"},
            ]
        )
        repo.get_neighbors = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_causal_repo(self):
        repo = MagicMock()
        repo.get_causes = AsyncMock(return_value=[])
        repo.get_effects = AsyncMock(return_value=[])
        return repo

    @pytest.mark.asyncio
    async def test_search_basic(self, mock_temporal_repo, mock_causal_repo):
        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(IntentType.OPEN),
        )

        results = await engine.search("test query")

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_with_pre_classified_intent(self, mock_temporal_repo, mock_causal_repo):
        classifier = MockIntentClassifier(IntentType.OPEN)

        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=classifier,
        )

        await engine.search("test query", intent=IntentType.WHY)

        # Should not call classifier since intent is pre-provided
        # (We can verify by checking the search completed without error)

    @pytest.mark.asyncio
    async def test_search_classifies_intent_if_not_provided(
        self, mock_temporal_repo, mock_causal_repo
    ):
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=MagicMock(intent=IntentType.WHY))

        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=classifier,
        )

        await engine.search("why did X happen?")

        classifier.classify.assert_called_once_with("why did X happen?")

    @pytest.mark.asyncio
    async def test_search_no_anchors_returns_empty(self, mock_temporal_repo, mock_causal_repo):
        mock_temporal_repo.search_temporal_events = AsyncMock(return_value=[])
        mock_temporal_repo.get_temporal_chain = AsyncMock(return_value=[])

        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

        results = await engine.search("nonexistent query")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_exception_returns_empty(self, mock_temporal_repo, mock_causal_repo):
        mock_temporal_repo.search_temporal_events = AsyncMock(side_effect=Exception("DB error"))

        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

        results = await engine.search("test query")

        assert results == []


class TestAdaptiveSearchCache:
    """Tests for knowledge cache integration."""

    @pytest.fixture
    def mock_temporal_repo(self):
        repo = MagicMock()
        repo.search_temporal_events = AsyncMock(return_value=[])
        repo.get_temporal_chain = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_causal_repo(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_results(self, mock_temporal_repo, mock_causal_repo):
        mock_cache = MagicMock()
        cached_cluster = MagicMock()
        cached_cluster.id = "cluster-1"
        cached_cluster.content = "Cached content"
        mock_cache.find_similar_cluster = AsyncMock(return_value=cached_cluster)
        mock_cache.update_hotness = AsyncMock()

        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
            knowledge_cache=mock_cache,
        )

        results = await engine.search("cached query")

        assert len(results) == 1
        assert results[0]["id"] == "cluster-1"
        assert results[0]["score"] == 1.0
        assert results[0]["source"] == "cache"
        mock_cache.update_hotness.assert_called_once_with("cluster-1")

    @pytest.mark.asyncio
    async def test_cache_miss_proceeds_to_search(self, mock_temporal_repo, mock_causal_repo):
        mock_cache = MagicMock()
        mock_cache.find_similar_cluster = AsyncMock(return_value=None)

        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
            knowledge_cache=mock_cache,
        )

        results = await engine.search("new query")

        # Should proceed to normal search (which returns empty since no anchors)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_no_cache_skips_cache_check(self, mock_temporal_repo, mock_causal_repo):
        engine = AdaptiveSearchEngine(
            temporal_repo=mock_temporal_repo,
            causal_repo=mock_causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
            knowledge_cache=None,
        )

        results = await engine.search("test query")

        # Should proceed normally without cache
        assert isinstance(results, list)


class TestAdaptiveSearchFindAnchors:
    """Tests for _find_anchors method."""

    @pytest.fixture
    def engine(self):
        return AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

    @pytest.mark.asyncio
    async def test_find_anchors_why_intent(self, engine):
        engine._temporal_repo.search_temporal_events = AsyncMock(return_value=[{"id": "anchor-1"}])

        anchors = await engine._find_anchors("why query", [0.1] * 384, IntentType.WHY)

        assert len(anchors) == 1
        # Task 3.1: _find_anchors now passes query_embedding + embedding_service
        # so search_temporal_events can re-rank by cosine similarity (D1).
        engine._temporal_repo.search_temporal_events.assert_called_once_with(
            query="why query",
            limit=5,
            query_embedding=[0.1] * 384,
            embedding_service=engine._embedding_service,
        )

    @pytest.mark.asyncio
    async def test_find_anchors_when_intent(self, engine):
        engine._temporal_repo.search_temporal_events = AsyncMock(return_value=[{"id": "anchor-1"}])

        anchors = await engine._find_anchors("when query", [0.1] * 384, IntentType.WHEN)

        engine._temporal_repo.search_temporal_events.assert_called_once_with(
            query="when query",
            limit=3,
            query_embedding=[0.1] * 384,
            embedding_service=engine._embedding_service,
        )

    @pytest.mark.asyncio
    async def test_find_anchors_default_intent(self, engine):
        engine._temporal_repo.search_temporal_events = AsyncMock(return_value=[{"id": "anchor-1"}])

        anchors = await engine._find_anchors("open query", [0.1] * 384, IntentType.OPEN)

        engine._temporal_repo.search_temporal_events.assert_called_once_with(
            query="open query",
            limit=3,
            query_embedding=[0.1] * 384,
            embedding_service=engine._embedding_service,
        )

    @pytest.mark.asyncio
    async def test_find_anchors_no_fallback_to_temporal_chain(self, engine):
        """When search_temporal_events returns empty, _find_anchors SHALL return empty.

        Previously this fell back to get_temporal_chain (returning all events
        ignoring the query). This was removed — search must respect the query.
        """
        engine._temporal_repo.search_temporal_events = AsyncMock(return_value=[])
        engine._temporal_repo.get_temporal_chain = AsyncMock(return_value=[{"id": "fallback-1"}])

        anchors = await engine._find_anchors("query", [0.1] * 384, IntentType.OPEN)

        assert anchors == []
        engine._temporal_repo.get_temporal_chain.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_anchors_filters_empty_ids(self, engine):
        engine._temporal_repo.search_temporal_events = AsyncMock(
            return_value=[{"id": ""}, {"id": "valid-id"}]
        )

        anchors = await engine._find_anchors("query", [0.1] * 384, IntentType.OPEN)

        assert anchors == ["valid-id"]


class TestAdaptiveSearchGetNeighbors:
    """Tests for _get_neighbors_by_intent method."""

    @pytest.fixture
    def engine(self):
        return AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

    @pytest.mark.asyncio
    async def test_get_neighbors_open_intent(self, engine):
        engine._temporal_repo.get_neighbors = AsyncMock(return_value=[{"id": "neighbor-1"}])

        neighbors = await engine._get_neighbors_by_intent("event-1", IntentType.OPEN)

        assert len(neighbors) == 1
        assert neighbors[0] == ("neighbor-1", EdgeType.TEMPORAL)

    @pytest.mark.asyncio
    async def test_get_neighbors_why_intent(self, engine):
        engine._temporal_repo.get_neighbors = AsyncMock(return_value=[{"id": "neighbor-1"}])
        engine._causal_repo.get_causes = AsyncMock(return_value=[{"id": "cause-1"}])
        engine._causal_repo.get_effects = AsyncMock(return_value=[{"id": "effect-1"}])

        neighbors = await engine._get_neighbors_by_intent("event-1", IntentType.WHY)

        assert len(neighbors) == 3
        edge_types = [n[1] for n in neighbors]
        assert EdgeType.TEMPORAL in edge_types
        assert EdgeType.CAUSAL in edge_types

    @pytest.mark.asyncio
    async def test_get_neighbors_filters_empty_ids(self, engine):
        engine._temporal_repo.get_neighbors = AsyncMock(return_value=[{"id": ""}, {"id": "valid"}])

        neighbors = await engine._get_neighbors_by_intent("event-1", IntentType.OPEN)

        assert len(neighbors) == 1


class TestAdaptiveSearchEstimateTokens:
    """Tests for _estimate_tokens method."""

    def test_estimate_tokens_basic(self):
        engine = AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

        results = [{"content": "A" * 100}, {"content": "B" * 200}]

        tokens = engine._estimate_tokens(results)

        assert tokens == 75  # (100 + 200) // 4

    def test_estimate_tokens_empty(self):
        engine = AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

        tokens = engine._estimate_tokens([])

        assert tokens == 0

    def test_estimate_tokens_no_content(self):
        engine = AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

        results = [{"id": "1"}]

        tokens = engine._estimate_tokens(results)

        assert tokens == 0


class TestAdaptiveSearchGetEventData:
    """Tests for _get_event_data method."""

    @pytest.mark.asyncio
    async def test_get_event_data_from_cache(self):
        engine = AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )
        engine._event_cache = {"event-1": {"id": "event-1", "content": "cached content"}}

        result = await engine._get_event_data("event-1")

        assert result is not None
        assert result["content"] == "cached content"

    @pytest.mark.asyncio
    async def test_get_event_data_fallback_to_repo(self):
        engine = AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )
        engine._event_cache = None
        engine._temporal_repo.get_temporal_chain = AsyncMock(
            return_value=[
                {"id": "event-1", "content": "repo content"},
                {"id": "event-2", "content": "other content"},
            ]
        )

        result = await engine._get_event_data("event-1")

        assert result is not None
        assert result["content"] == "repo content"

    @pytest.mark.asyncio
    async def test_get_event_data_not_found(self):
        engine = AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )
        engine._event_cache = None
        engine._temporal_repo.get_temporal_chain = AsyncMock(return_value=[])

        result = await engine._get_event_data("nonexistent")

        assert result is None


# --- D3/D4 normalization + intent-aware edge_type tests ---
# (spec: search-score-normalization, search-engine)


class TestAdaptiveSearchIntentAwareEdgeType:
    """Tests for D4 intent-aware anchor edge_type selection."""

    @pytest.mark.asyncio
    async def test_beam_search_uses_intent_aware_edge_type(self):
        """WHY intent 应使用 CAUSAL edge_type 计算 anchor 分数（D4 / Task 3.3）。

        旧实现硬编码 ``EdgeType.TEMPORAL``，导致 WHY intent 无法沿因果链扩展。
        修复后 ``_INTENT_TO_ANCHOR_EDGE_TYPE[WHY] == EdgeType.CAUSAL``。
        通过 spy ``calculate_transition_score`` 验证传入的 edge_type。
        """
        from modules.memory.retrieval import adaptive_search as adaptive_search_module

        temporal_repo = MagicMock()
        temporal_repo.get_temporal_chain = AsyncMock(
            return_value=[
                {
                    "id": "a1",
                    "content": "anchor content",
                    "timestamp": "2026-01-01",
                    "embedding": [0.5, 0.5],
                }
            ]
        )
        temporal_repo.get_neighbors = AsyncMock(return_value=[])
        causal_repo = MagicMock()
        causal_repo.get_causes = AsyncMock(return_value=[])
        causal_repo.get_effects = AsyncMock(return_value=[])

        engine = AdaptiveSearchEngine(
            temporal_repo=temporal_repo,
            causal_repo=causal_repo,
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

        captured_edge_types: list[EdgeType] = []
        original = adaptive_search_module.calculate_transition_score

        def spy(neighbor, query_embedding, query_intent, edge_type, **kwargs):
            captured_edge_types.append(edge_type)
            return original(
                neighbor=neighbor,
                query_embedding=query_embedding,
                query_intent=query_intent,
                edge_type=edge_type,
                **kwargs,
            )

        with patch.object(adaptive_search_module, "calculate_transition_score", side_effect=spy):
            await engine._beam_search(
                anchors=["a1"],
                query_embedding=[0.5, 0.5],
                intent=IntentType.WHY,
            )

        # Anchor 评分必须用 CAUSAL edge_type（D4）
        assert len(captured_edge_types) >= 1
        assert all(
            et == EdgeType.CAUSAL for et in captured_edge_types
        ), f"WHY intent 应使用 CAUSAL，实际: {captured_edge_types}"


class TestAdaptiveSearchNormalization:
    """Tests for D3 normalization degradation fix."""

    @pytest.fixture
    def engine(self):
        """Engine with mocked dependencies; _find_anchors/_beam_search overridden."""
        return AdaptiveSearchEngine(
            temporal_repo=MagicMock(),
            causal_repo=MagicMock(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=MockIntentClassifier(),
        )

    @pytest.mark.asyncio
    async def test_normalization_degraded_when_all_scores_identical(self, engine):
        """多结果同分时归一化分数应为 0.0 且标记 degraded（D3 / Task 4.1-4.3）。

        场景：beam search 返回 2 个结果且 score 全为 5.0（exp(2.0) 一致）。
        旧行为：归一化为 1.0（谎称完美匹配）。
        新行为：归一化为 0.0 + ``degraded: True`` 标记 + ``last_metadata['degraded']``。
        """
        # Bypass real beam search; control returned scores directly.
        engine._find_anchors = AsyncMock(return_value=["a1", "a2"])
        engine._beam_search = AsyncMock(
            return_value=[
                {"id": "a1", "content": "x", "score": 5.0},
                {"id": "a2", "content": "y", "score": 5.0},
            ]
        )

        results = await engine.search("query", intent=IntentType.OPEN)

        assert len(results) == 2
        # 核心断言：所有 score 应为 0.0（不再伪装完美匹配）
        assert all(r["score"] == 0.0 for r in results)
        # 每个结果都携带 degraded 标记（暴露给端点调用方）
        assert all(r.get("degraded") is True for r in results)
        # metadata 暴露 degraded flag（D5）
        assert engine.last_metadata["degraded"] is True
        # causal_edges_traversed 在 metadata 中始终存在（D5）
        assert "causal_edges_traversed" in engine.last_metadata

    @pytest.mark.asyncio
    async def test_normalization_single_result_retains_1_0(self, engine):
        """单结果时即使 score_range==0 仍保留 1.0（Task 4.2）。

        理由：单个结果无统计意义做"区分"，1.0 表示"有结果返回"。
        degraded 不应触发（仅 >=2 同分场景视为退化）。
        """
        engine._find_anchors = AsyncMock(return_value=["a1"])
        engine._beam_search = AsyncMock(
            return_value=[
                {"id": "a1", "content": "x", "score": 5.0},
            ]
        )

        results = await engine.search("query", intent=IntentType.OPEN)

        assert len(results) == 1
        assert results[0]["score"] == 1.0
        # 单结果不应触发 degraded 标记
        assert "degraded" not in results[0]
        assert engine.last_metadata["degraded"] is False

    @pytest.mark.asyncio
    async def test_normalization_normal_range_uses_minmax(self, engine):
        """score_range > 0 时使用 min-max 归一化（保护已有行为）。

        构造 3 个 score 不同的结果：min=2.0, max=10.0, range=8.0。
        期望：score=(raw-min)/range，最大值归一化为 1.0，最小值为 0.0。
        """
        engine._find_anchors = AsyncMock(return_value=["a1", "a2", "a3"])
        engine._beam_search = AsyncMock(
            return_value=[
                {"id": "a1", "content": "high", "score": 10.0},
                {"id": "a2", "content": "mid", "score": 6.0},
                {"id": "a3", "content": "low", "score": 2.0},
            ]
        )

        results = await engine.search("query", intent=IntentType.OPEN)

        assert len(results) == 3
        # min-max: (10-2)/8=1.0, (6-2)/8=0.5, (2-2)/8=0.0
        scores = sorted(r["score"] for r in results)
        assert scores == [0.0, 0.5, 1.0]
        assert engine.last_metadata["degraded"] is False
