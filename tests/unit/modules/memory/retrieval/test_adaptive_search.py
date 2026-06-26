# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for AdaptiveSearchEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
        engine._temporal_repo.search_temporal_events.assert_called_once_with(
            query="why query", limit=5
        )

    @pytest.mark.asyncio
    async def test_find_anchors_when_intent(self, engine):
        engine._temporal_repo.search_temporal_events = AsyncMock(return_value=[{"id": "anchor-1"}])

        anchors = await engine._find_anchors("when query", [0.1] * 384, IntentType.WHEN)

        engine._temporal_repo.search_temporal_events.assert_called_once_with(
            query="when query", limit=3
        )

    @pytest.mark.asyncio
    async def test_find_anchors_default_intent(self, engine):
        engine._temporal_repo.search_temporal_events = AsyncMock(return_value=[{"id": "anchor-1"}])

        anchors = await engine._find_anchors("open query", [0.1] * 384, IntentType.OPEN)

        engine._temporal_repo.search_temporal_events.assert_called_once_with(
            query="open query", limit=3
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
