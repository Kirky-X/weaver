# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for TemporalGraphRepo."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.core.event_node import EventNode
from modules.memory.graphs.temporal import TemporalGraphRepo


@pytest.fixture
def mock_pool():
    """Create mock Neo4j pool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def repo(mock_pool):
    """Create TemporalGraphRepo with mock pool."""
    return TemporalGraphRepo(pool=mock_pool)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_to_chain_creates_event_node(repo, mock_pool):
    """Test that append_to_chain creates EventNode in Neo4j."""
    event = EventNode(
        id="event-001",
        content="Test event content",
        timestamp=datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC),
        attributes={"title": "Test Title"},
    )

    mock_pool.execute_query.return_value = [{"created": "event-001"}]

    result = await repo.append_to_chain(event)

    assert result is True
    mock_pool.execute_query.assert_called_once()

    # Verify query contains EventNode creation
    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0] if call_args[0] else call_args.kwargs.get("query", "")
    assert "EventNode" in query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_to_chain_links_to_previous(repo, mock_pool):
    """Test that append_to_chain creates FOLLOWED_BY relationship."""
    event = EventNode(
        id="event-002",
        content="Second event",
        timestamp=datetime(2026, 4, 2, 13, 0, 0, tzinfo=UTC),
    )

    mock_pool.execute_query.return_value = [{"linked": 1}]

    await repo.append_to_chain(event)

    call_args = mock_pool.execute_query.call_args
    query = call_args[0][0] if call_args[0] else call_args.kwargs.get("query", "")
    assert "FOLLOWED_BY" in query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_temporal_chain(repo, mock_pool):
    """Test retrieving temporal chain of events."""
    mock_pool.execute_query.return_value = [
        {"id": "event-001", "content": "First", "timestamp": "2026-04-02T12:00:00Z"},
        {"id": "event-002", "content": "Second", "timestamp": "2026-04-02T13:00:00Z"},
    ]

    events = await repo.get_temporal_chain(limit=10)

    assert len(events) == 2
    assert events[0]["id"] == "event-001"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors(repo, mock_pool):
    """Test getting temporal neighbors of an event."""
    mock_pool.execute_query.return_value = [
        {"id": "prev-event", "direction": "previous"},
        {"id": "next-event", "direction": "next"},
    ]

    neighbors = await repo.get_neighbors("event-001")

    assert len(neighbors) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_constraints(repo, mock_pool):
    """Test that constraints are created."""
    mock_pool.execute_query.return_value = []

    await repo.ensure_constraints()

    # Should be called for constraint creation
    assert mock_pool.execute_query.call_count >= 1
