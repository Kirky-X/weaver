# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for MemoryIntegrationService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.graph_types import IntentType
from modules.memory.integration.memory_service import (
    MemoryIntegrationService,
    MemoryServiceConfig,
)


@pytest.fixture
def mock_neo4j_pool():
    """Create mock Neo4j pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock(return_value=[])
    return pool


@pytest.fixture
def mock_llm_client():
    """Create mock LLM client."""
    client = MagicMock()
    client.call = AsyncMock(return_value='{"causal_edges": []}')
    return client


@pytest.fixture
def mock_redis_client():
    """Create mock Redis client."""
    redis = MagicMock()
    redis.lpush = AsyncMock(return_value=1)
    redis.rpop = AsyncMock(return_value=None)
    redis.llen = AsyncMock(return_value=0)
    return redis


@pytest.fixture
def mock_embedding_service():
    """Create mock embedding service."""
    service = MagicMock()
    service.embed = AsyncMock(return_value=[0.1] * 384)
    return service


@pytest.fixture
def mock_intent_classifier():
    """Create mock intent classifier."""
    classifier = MagicMock()
    classification = MagicMock()
    classification.intent = IntentType.OPEN
    classifier.classify = AsyncMock(return_value=classification)
    return classifier


@pytest.fixture
def memory_service(
    mock_neo4j_pool,
    mock_llm_client,
    mock_redis_client,
    mock_embedding_service,
    mock_intent_classifier,
):
    """Create MemoryIntegrationService with mocks."""
    return MemoryIntegrationService(
        neo4j_pool=mock_neo4j_pool,
        llm_client=mock_llm_client,
        redis_client=mock_redis_client,
        embedding_service=mock_embedding_service,
        intent_classifier=mock_intent_classifier,
    )


@pytest.mark.unit
def test_config_defaults():
    """Test MemoryServiceConfig has correct defaults."""
    config = MemoryServiceConfig()

    assert config.fast_path_enabled is True
    assert config.slow_path_enabled is True
    assert config.causal_confidence_threshold == 0.7
    assert config.max_traversal_depth == 5
    assert config.beam_width == 10
    assert config.token_budget == 4000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_creates_constraints(memory_service, mock_neo4j_pool):
    """Test that initialize creates constraints."""
    await memory_service.initialize()

    # Should call execute_query for constraint creation
    assert mock_neo4j_pool.execute_query.call_count >= 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_creates_event(memory_service, mock_neo4j_pool):
    """Test that ingest creates an EventNode."""
    mock_neo4j_pool.execute_query.return_value = [{"created": 1}]

    state = {
        "article_id": "article-001",
        "cleaned": {"title": "Test Article", "content": "Test content"},
        "raw": MagicMock(
            publish_time=datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC),
            url="https://example.com",
        ),
        "vectors": {"content": [0.1] * 384},
        "entities": [],
    }

    event = await memory_service.ingest(state)

    assert event is not None
    assert event.id == "article-001"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_disabled():
    """Test that ingest returns None when fast path disabled."""
    config = MemoryServiceConfig(fast_path_enabled=False)

    service = MemoryIntegrationService(
        neo4j_pool=MagicMock(),
        llm_client=MagicMock(),
        redis_client=MagicMock(),
        embedding_service=MagicMock(),
        intent_classifier=MagicMock(),
        config=config,
    )

    result = await service.ingest({"article_id": "test"})

    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_consolidate_processes_queue(memory_service, mock_redis_client):
    """Test that consolidate processes events from queue."""
    mock_redis_client.rpop.side_effect = ["event-001", "event-002", None]

    results = await memory_service.consolidate(batch_size=5)

    assert len(results) == 2
    assert results[0].event_id == "event-001"
    assert results[1].event_id == "event-002"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_consolidate_disabled():
    """Test that consolidate returns empty when slow path disabled."""
    config = MemoryServiceConfig(slow_path_enabled=False)

    service = MemoryIntegrationService(
        neo4j_pool=MagicMock(),
        llm_client=MagicMock(),
        redis_client=MagicMock(),
        embedding_service=MagicMock(),
        intent_classifier=MagicMock(),
        config=config,
    )

    results = await service.consolidate()

    assert results == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_delegates_to_engine(memory_service, mock_embedding_service):
    """Test that search delegates to AdaptiveSearchEngine."""
    results = await memory_service.search("Why did this happen?")

    mock_embedding_service.embed.assert_called_once()
    assert isinstance(results, list)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_with_provided_intent(memory_service, mock_intent_classifier):
    """Test search with pre-classified intent."""
    results = await memory_service.search(
        "Test query",
        intent=IntentType.WHY,
    )

    # Should not call classifier when intent is provided
    mock_intent_classifier.classify.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_queue_depth(memory_service, mock_redis_client):
    """Test getting queue depth."""
    mock_redis_client.llen.return_value = 5

    depth = await memory_service.get_queue_depth()

    assert depth == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_check(memory_service, mock_redis_client):
    """Test health check returns status."""
    mock_redis_client.llen.return_value = 3

    health = await memory_service.health_check()

    assert health["status"] == "healthy"
    assert health["fast_path_enabled"] is True
    assert health["slow_path_enabled"] is True
    assert health["queue_depth"] == 3


@pytest.mark.unit
def test_temporal_repo_property(memory_service):
    """Test temporal_repo property."""
    repo = memory_service.temporal_repo
    assert repo is not None


@pytest.mark.unit
def test_causal_repo_property(memory_service):
    """Test causal_repo property."""
    repo = memory_service.causal_repo
    assert repo is not None


@pytest.mark.unit
def test_search_engine_property(memory_service):
    """Test search_engine property."""
    engine = memory_service.search_engine
    assert engine is not None
