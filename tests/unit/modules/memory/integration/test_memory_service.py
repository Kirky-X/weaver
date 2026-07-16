# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for MemoryIntegrationService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.memory.core.graph_types import IntentType
from modules.memory.integration.memory_service import (
    _QUERY_INTENT_TO_MEMORY_INTENT,
    IntentClassifierAdapter,
    MemoryIntegrationService,
    MemoryServiceConfig,
)


class MockEmbeddingService:
    """Mock embedding service for tests."""

    async def embed(self, text: str) -> list[float]:
        return [0.0] * 384


def _make_mock_graph_pool():
    pool = MagicMock()
    pool.database_type = "ladybug"
    pool.execute_query = AsyncMock(return_value=[])
    return pool


def _make_mock_llm():
    llm = MagicMock()
    llm.call = AsyncMock(return_value='{"result": "success"}')
    llm.call_at = AsyncMock(return_value='{"result": "success"}')
    return llm


def _make_mock_redis():
    redis = MagicMock()
    redis.lpush = AsyncMock(return_value=True)
    redis.rpop = AsyncMock(return_value=None)
    redis.llen = AsyncMock(return_value=0)
    return redis


def _make_mock_intent_classifier():
    classifier = MagicMock()
    classifier.classify = AsyncMock()
    classifier.classify.return_value = MagicMock(intent=MagicMock(value="open"))
    return classifier


class TestMemoryServiceIngest:
    """Tests for MemoryIntegrationService.ingest()."""

    @pytest.mark.asyncio
    async def test_ingest_calls_fast_path(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._fast_path.ingest = AsyncMock(return_value=MagicMock(id="event-1", content="test"))

        result = await service.ingest({"article_id": "test", "cleaned": {"title": "Test"}})

        service._fast_path.ingest.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_ingest_disabled_fast_path(self):
        config = MemoryServiceConfig(fast_path_enabled=False)
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            config=config,
        )

        result = await service.ingest({"article_id": "test"})

        assert result is None

    @pytest.mark.asyncio
    async def test_ingest_passes_state(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._fast_path.ingest = AsyncMock(return_value=None)

        state = {"article_id": "test-123", "cleaned": {"title": "Test"}}
        await service.ingest(state)

        service._fast_path.ingest.assert_called_once_with(state)


class TestMemoryServiceConsolidate:
    """Tests for MemoryIntegrationService.consolidate()."""

    @pytest.mark.asyncio
    async def test_consolidate_calls_slow_path(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._slow_path.process_batch = AsyncMock(return_value=[])

        await service.consolidate(batch_size=5)

        service._slow_path.process_batch.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_consolidate_disabled_slow_path(self):
        config = MemoryServiceConfig(slow_path_enabled=False)
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            config=config,
        )

        result = await service.consolidate()

        assert result == []

    @pytest.mark.asyncio
    async def test_consolidate_default_batch_size(self):
        config = MemoryServiceConfig(consolidation_batch_size=15)
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            config=config,
        )
        service._slow_path.process_batch = AsyncMock(return_value=[])

        await service.consolidate()

        service._slow_path.process_batch.assert_called_once_with(15)

    @pytest.mark.asyncio
    async def test_consolidate_custom_batch_size(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._slow_path.process_batch = AsyncMock(return_value=[])

        await service.consolidate(batch_size=20)

        service._slow_path.process_batch.assert_called_once_with(20)


class TestMemoryServiceSearch:
    """Tests for MemoryIntegrationService.search()."""

    @pytest.mark.asyncio
    async def test_search_delegates_to_engine(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._search_engine.search = AsyncMock(
            return_value=[{"id": "1", "content": "test", "score": 0.9}]
        )

        result = await service.search("test query")

        service._search_engine.search.assert_called_once_with("test query", None, None)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_with_anchors_and_intent(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._search_engine.search = AsyncMock(return_value=[])

        await service.search(
            "why did X happen?",
            anchors=["anchor-1"],
            intent=IntentType.WHY,
        )

        service._search_engine.search.assert_called_once_with(
            "why did X happen?", ["anchor-1"], IntentType.WHY
        )


class TestMemoryServiceSearchWithContext:
    """Tests for MemoryIntegrationService.search_with_context()."""

    @pytest.mark.asyncio
    async def test_raises_without_entity_repo(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            entity_repo=None,
        )

        with pytest.raises(RuntimeError, match="entity_repo to be injected"):
            await service.search_with_context("test query")

    @pytest.mark.asyncio
    async def test_context_mode(self):
        mock_entity_repo = MagicMock()
        mock_entity_repo.get_entity_neighborhood = AsyncMock(return_value=None)

        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            entity_repo=mock_entity_repo,
        )
        service._response_builder.build = AsyncMock(
            return_value={"query": "test", "answer": "result", "output_mode": "CONTEXT"}
        )

        result = await service.search_with_context("test query", output_mode="context")

        assert result["output_mode"] == "CONTEXT"

    @pytest.mark.asyncio
    async def test_narrative_mode(self):
        mock_entity_repo = MagicMock()
        mock_entity_repo.get_entity_neighborhood = AsyncMock(return_value=None)

        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            entity_repo=mock_entity_repo,
        )
        service._response_builder.build = AsyncMock(
            return_value={"query": "test", "answer": "narrative result", "output_mode": "NARRATIVE"}
        )

        result = await service.search_with_context("test query", output_mode="narrative")

        assert result["output_mode"] == "NARRATIVE"

    @pytest.mark.asyncio
    async def test_with_entity_enrichment(self):
        mock_entity_repo = MagicMock()
        mock_entity_repo.get_entity_neighborhood = AsyncMock(return_value=None)

        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            entity_repo=mock_entity_repo,
        )
        service._response_builder.build = AsyncMock(
            return_value={"query": "test", "entities": [{"entity": "A"}]}
        )

        result = await service.search_with_context("test query", enrich_entities=True)

        # Verify build was called with correct params
        call_kwargs = service._response_builder.build.call_args.kwargs
        assert call_kwargs["query"] == "test query"
        assert call_kwargs["enrich_entities"] is True


class TestMemoryServiceHealthCheck:
    """Tests for MemoryIntegrationService.health_check()."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._consolidation_queue.length = AsyncMock(return_value=5)

        result = await service.health_check()

        assert result["status"] == "healthy"
        assert result["queue_depth"] == 5
        assert result["fast_path_enabled"] is True
        assert result["slow_path_enabled"] is True

    @pytest.mark.asyncio
    async def test_health_check_disabled_paths(self):
        config = MemoryServiceConfig(fast_path_enabled=False, slow_path_enabled=False)
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
            config=config,
        )
        service._consolidation_queue.length = AsyncMock(return_value=0)

        result = await service.health_check()

        assert result["fast_path_enabled"] is False
        assert result["slow_path_enabled"] is False


class TestMemoryServiceInitialize:
    """Tests for MemoryIntegrationService.initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_creates_constraints(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._temporal_repo.ensure_constraints = AsyncMock()
        service._causal_repo.ensure_constraints = AsyncMock()

        await service.initialize()

        service._temporal_repo.ensure_constraints.assert_called_once()
        service._causal_repo.ensure_constraints.assert_called_once()


class TestMemoryServiceProperties:
    """Tests for MemoryIntegrationService properties."""

    def test_temporal_repo_property(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )

        assert service.temporal_repo is service._temporal_repo

    def test_causal_repo_property(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )

        assert service.causal_repo is service._causal_repo

    def test_search_engine_property(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )

        assert service.search_engine is service._search_engine


class TestMemoryServiceGetQueueDepth:
    """Tests for MemoryIntegrationService.get_queue_depth()."""

    @pytest.mark.asyncio
    async def test_get_queue_depth(self):
        service = MemoryIntegrationService(
            graph_pool=_make_mock_graph_pool(),
            llm_client=_make_mock_llm(),
            cache=_make_mock_redis(),
            embedding_service=MockEmbeddingService(),
            intent_classifier=_make_mock_intent_classifier(),
        )
        service._consolidation_queue.length = AsyncMock(return_value=10)

        depth = await service.get_queue_depth()

        assert depth == 10


class TestIntentClassifierAdapter:
    """Tests for IntentClassifierAdapter."""

    @pytest.mark.asyncio
    async def test_classify_maps_why(self):
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=MagicMock(intent=MagicMock(value="why")))

        adapter = IntentClassifierAdapter(classifier)
        result = await adapter.classify("Why did X happen?")

        assert result.intent == IntentType.WHY

    @pytest.mark.asyncio
    async def test_classify_maps_when(self):
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=MagicMock(intent=MagicMock(value="when")))

        adapter = IntentClassifierAdapter(classifier)
        result = await adapter.classify("When did Y occur?")

        assert result.intent == IntentType.WHEN

    @pytest.mark.asyncio
    async def test_classify_maps_entity(self):
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=MagicMock(intent=MagicMock(value="entity")))

        adapter = IntentClassifierAdapter(classifier)
        result = await adapter.classify("What is Z?")

        assert result.intent == IntentType.ENTITY

    @pytest.mark.asyncio
    async def test_classify_maps_open(self):
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=MagicMock(intent=MagicMock(value="open")))

        adapter = IntentClassifierAdapter(classifier)
        result = await adapter.classify("Tell me about W")

        assert result.intent == IntentType.OPEN

    @pytest.mark.asyncio
    async def test_classify_unknown_defaults_to_open(self):
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=MagicMock(intent=MagicMock(value="unknown")))

        adapter = IntentClassifierAdapter(classifier)
        result = await adapter.classify("Unknown intent query")

        assert result.intent == IntentType.OPEN

    @pytest.mark.asyncio
    async def test_classify_multi_hop_maps_to_open(self):
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=MagicMock(intent=MagicMock(value="multi_hop")))

        adapter = IntentClassifierAdapter(classifier)
        result = await adapter.classify("Multi-hop query")

        assert result.intent == IntentType.OPEN


class TestMemoryServiceConfig:
    """Tests for MemoryServiceConfig."""

    def test_default_config(self):
        config = MemoryServiceConfig()
        assert config.fast_path_enabled is True
        assert config.slow_path_enabled is True
        assert config.causal_confidence_threshold == 0.7
        assert config.consolidation_batch_size == 10

    def test_custom_config(self):
        config = MemoryServiceConfig(
            fast_path_enabled=False,
            slow_path_enabled=False,
            consolidation_batch_size=20,
        )
        assert config.fast_path_enabled is False
        assert config.slow_path_enabled is False
        assert config.consolidation_batch_size == 20
