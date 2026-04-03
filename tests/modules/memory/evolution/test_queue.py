# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for ConsolidationQueue."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.evolution.queue import ConsolidationQueue
from modules.memory.evolution.result import ConsolidationResult


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    redis = MagicMock()
    redis.lpush = AsyncMock(return_value=1)
    redis.rpop = AsyncMock(return_value=None)
    redis.llen = AsyncMock(return_value=0)
    return redis


@pytest.fixture
def queue(mock_redis):
    """Create ConsolidationQueue with mock Redis."""
    return ConsolidationQueue(redis=mock_redis, key_prefix="test:consolidation")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_event(queue, mock_redis):
    """Test adding event to consolidation queue."""
    await queue.enqueue("event-001")

    mock_redis.lpush.assert_called_once()
    call_args = mock_redis.lpush.call_args
    assert "test:consolidation:pending" in call_args[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dequeue_event(queue, mock_redis):
    """Test removing event from consolidation queue."""
    mock_redis.rpop.return_value = "event-002"

    result = await queue.dequeue()

    assert result == "event-002"
    mock_redis.rpop.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dequeue_empty_queue(queue, mock_redis):
    """Test dequeue from empty queue returns None."""
    mock_redis.rpop.return_value = None

    result = await queue.dequeue()

    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_queue_length(queue, mock_redis):
    """Test getting queue length."""
    mock_redis.llen.return_value = 5

    length = await queue.length()

    assert length == 5


@pytest.mark.unit
def test_consolidation_result():
    """Test ConsolidationResult dataclass."""
    result = ConsolidationResult(
        event_id="event-001",
        causal_edges_added=3,
        entity_links_added=5,
        confidence_avg=0.82,
    )

    assert result.event_id == "event-001"
    assert result.causal_edges_added == 3
    assert result.entity_links_added == 5
    assert result.confidence_avg == 0.82
