# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for SynapticIngestionService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.evolution.fast_path import SynapticIngestionService


@pytest.fixture
def mock_temporal_repo():
    """Create mock temporal repository."""
    repo = MagicMock()
    repo.append_to_chain = AsyncMock(return_value=True)
    repo.ensure_constraints = AsyncMock()
    return repo


@pytest.fixture
def mock_vector_repo():
    """Create mock vector repository."""
    repo = MagicMock()
    repo.upsert_event_embedding = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_entity_repo():
    """Create mock entity repository."""
    repo = MagicMock()
    repo.link_entities = AsyncMock(return_value=2)
    return repo


@pytest.fixture
def mock_queue():
    """Create mock consolidation queue."""
    queue = MagicMock()
    queue.enqueue = AsyncMock(return_value=True)
    return queue


@pytest.fixture
def service(mock_temporal_repo, mock_vector_repo, mock_entity_repo, mock_queue):
    """Create SynapticIngestionService with mocks."""
    return SynapticIngestionService(
        temporal_repo=mock_temporal_repo,
        vector_repo=mock_vector_repo,
        entity_repo=mock_entity_repo,
        consolidation_queue=mock_queue,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_creates_event_node(service, mock_temporal_repo):
    """Test that ingest creates EventNode in temporal graph."""
    state = {
        "article_id": "article-001",
        "cleaned": {"title": "Test", "content": "Content"},
        "raw": MagicMock(
            publish_time=datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC),
            url="https://example.com",
        ),
        "vectors": {"content": [0.1] * 384},
        "entities": [{"name": "Entity1", "type": "Person"}],
    }

    event = await service.ingest(state)

    assert event is not None
    assert event.id == "article-001"
    mock_temporal_repo.append_to_chain.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_indexes_embedding(service, mock_vector_repo):
    """Test that ingest indexes event embedding."""
    state = {
        "article_id": "article-002",
        "cleaned": {"title": "Test", "content": "Content"},
        "raw": MagicMock(
            publish_time=datetime.now(UTC),
            url="https://example.com",
        ),
        "vectors": {"content": [0.2] * 384},
        "entities": [],
    }

    await service.ingest(state)

    mock_vector_repo.upsert_event_embedding.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_links_entities(service, mock_entity_repo):
    """Test that ingest links entities to event."""
    state = {
        "article_id": "article-003",
        "cleaned": {"title": "Test", "content": "Content"},
        "raw": MagicMock(
            publish_time=datetime.now(UTC),
            url="https://example.com",
        ),
        "vectors": {},
        "entities": [
            {"name": "Entity1", "type": "Person"},
            {"name": "Entity2", "type": "Organization"},
        ],
    }

    await service.ingest(state)

    mock_entity_repo.link_entities.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_triggers_slow_path(service, mock_queue):
    """Test that ingest triggers slow path consolidation."""
    state = {
        "article_id": "article-004",
        "cleaned": {"title": "Test", "content": "Content"},
        "raw": MagicMock(
            publish_time=datetime.now(UTC),
            url="https://example.com",
        ),
        "vectors": {},
        "entities": [],
    }

    await service.ingest(state)

    mock_queue.enqueue.assert_called_once_with("article-004")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_handles_missing_data(service, mock_temporal_repo):
    """Test that ingest handles missing optional data gracefully."""
    state = {
        "article_id": "article-005",
        "cleaned": {},
        "raw": None,
        "vectors": None,
        "entities": None,
    }

    event = await service.ingest(state)

    # Should still create an event
    assert event is not None
    assert event.id == "article-005"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_without_optional_deps(mock_temporal_repo):
    """Test ingest works without optional dependencies."""
    service = SynapticIngestionService(
        temporal_repo=mock_temporal_repo,
        vector_repo=None,
        entity_repo=None,
        consolidation_queue=None,
    )

    state = {
        "article_id": "article-006",
        "cleaned": {"title": "Test", "content": "Content"},
        "raw": MagicMock(
            publish_time=datetime.now(UTC),
            url="https://example.com",
        ),
        "vectors": {"content": [0.1] * 384},
        "entities": [{"name": "Entity1"}],
    }

    event = await service.ingest(state)

    assert event is not None
    mock_temporal_repo.append_to_chain.assert_called_once()
