# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.processing.queue module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.processing.queue import MAX_QUEUE_SIZE, QUEUE_KEY, ProcessingQueue


@pytest.fixture
def mock_cache():
    """Create a mock CachePool."""
    cache = AsyncMock()
    cache.llen = AsyncMock(return_value=0)
    cache.lpush = AsyncMock()
    cache.rpop = AsyncMock(return_value=None)
    cache.lrange = AsyncMock(return_value=[])
    cache.ltrim = AsyncMock()
    cache.delete = AsyncMock()
    return cache


@pytest.fixture
def queue(mock_cache):
    return ProcessingQueue(mock_cache)


class TestProcessingQueueInit:
    def test_init(self, mock_cache):
        q = ProcessingQueue(mock_cache)
        assert q._cache is mock_cache

    def test_queue_key_constant(self):
        assert QUEUE_KEY == "weaver:processing:pending"

    def test_max_queue_size_constant(self):
        assert MAX_QUEUE_SIZE == 200


class TestEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_valid_uuid(self, queue, mock_cache):
        mock_cache.llen.return_value = 5
        result = await queue.enqueue("550e8400-e29b-41d4-a716-446655440000")
        assert result is True
        mock_cache.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_with_task_id(self, queue, mock_cache):
        mock_cache.llen.return_value = 5
        result = await queue.enqueue("550e8400-e29b-41d4-a716-446655440000", "task-123")
        assert result is True
        call_args = mock_cache.lpush.call_args
        payload = call_args[0][1]
        assert payload == "550e8400-e29b-41d4-a716-446655440000:task-123"

    @pytest.mark.asyncio
    async def test_enqueue_without_task_id(self, queue, mock_cache):
        mock_cache.llen.return_value = 5
        await queue.enqueue("550e8400-e29b-41d4-a716-446655440000")
        payload = mock_cache.lpush.call_args[0][1]
        assert payload.endswith(":")

    @pytest.mark.asyncio
    async def test_enqueue_invalid_uuid(self, queue):
        with pytest.raises(ValueError, match="Invalid UUID format"):
            await queue.enqueue("not-a-uuid")

    @pytest.mark.asyncio
    async def test_enqueue_queue_full(self, queue, mock_cache):
        mock_cache.llen.return_value = MAX_QUEUE_SIZE
        result = await queue.enqueue("550e8400-e29b-41d4-a716-446655440000")
        assert result is False
        mock_cache.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueue_queue_near_full(self, queue, mock_cache):
        mock_cache.llen.return_value = MAX_QUEUE_SIZE - 1
        result = await queue.enqueue("550e8400-e29b-41d4-a716-446655440000")
        assert result is True


class TestDequeue:
    @pytest.mark.asyncio
    async def test_dequeue_empty(self, queue, mock_cache):
        mock_cache.rpop.return_value = None
        result = await queue.dequeue()
        assert result is None

    @pytest.mark.asyncio
    async def test_dequeue_with_task_id(self, queue, mock_cache):
        mock_cache.rpop.return_value = "article-id-1:task-123"
        result = await queue.dequeue()
        assert result == ("article-id-1", "task-123")

    @pytest.mark.asyncio
    async def test_dequeue_without_task_id(self, queue, mock_cache):
        mock_cache.rpop.return_value = "article-id-1:"
        result = await queue.dequeue()
        assert result == ("article-id-1", None)

    @pytest.mark.asyncio
    async def test_dequeue_payload_with_colon_in_task(self, queue, mock_cache):
        """Test dequeue with colon in task ID - only first segment after colon is captured."""
        mock_cache.rpop.return_value = "article-id-1:task:with:colons"
        result = await queue.dequeue()
        # split(":") produces ["article-id-1", "task", "with", "colons"]
        # parts[1] is "task", not "task:with:colons"
        assert result == ("article-id-1", "task")


class TestDequeueBatch:
    @pytest.mark.asyncio
    async def test_dequeue_batch_empty(self, queue, mock_cache):
        mock_cache.llen.return_value = 0
        result = await queue.dequeue_batch(10)
        assert result == []

    @pytest.mark.asyncio
    async def test_dequeue_batch_zero_size(self, queue):
        result = await queue.dequeue_batch(0)
        assert result == []

    @pytest.mark.asyncio
    async def test_dequeue_batch_partial(self, queue, mock_cache):
        mock_cache.llen.return_value = 5
        mock_cache.lrange.return_value = [
            "id1:t1",
            "id2:t2",
            "id3:",
        ]
        result = await queue.dequeue_batch(3)
        assert len(result) == 3
        assert result[0] == ("id1", "t1")
        assert result[1] == ("id2", "t2")
        assert result[2] == ("id3", None)
        mock_cache.ltrim.assert_called_once()

    @pytest.mark.asyncio
    async def test_dequeue_batch_all_items(self, queue, mock_cache):
        mock_cache.llen.return_value = 2
        mock_cache.lrange.return_value = ["id1:t1", "id2:t2"]
        result = await queue.dequeue_batch(5)
        assert len(result) == 2
        mock_cache.delete.assert_called_once_with(QUEUE_KEY)

    @pytest.mark.asyncio
    async def test_dequeue_batch_lrange_negative_indices(self, queue, mock_cache):
        mock_cache.llen.return_value = 10
        mock_cache.lrange.return_value = ["id1:t1"]
        await queue.dequeue_batch(1)
        mock_cache.lrange.assert_called_once_with(QUEUE_KEY, -1, -1)


class TestLengthAndClear:
    @pytest.mark.asyncio
    async def test_length(self, queue, mock_cache):
        mock_cache.llen.return_value = 42
        result = await queue.length()
        assert result == 42

    @pytest.mark.asyncio
    async def test_clear(self, queue, mock_cache):
        mock_cache.rpop.side_effect = ["item1", "item2", None]
        await queue.clear()
        assert mock_cache.rpop.call_count == 3
