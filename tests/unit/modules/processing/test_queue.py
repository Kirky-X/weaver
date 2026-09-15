# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.processing.queue module."""

import asyncio
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
        # clear() is now a single atomic delete (O(1)) — the old rpop loop
        # could consume items LPUSHed concurrently mid-loop.
        await queue.clear()
        mock_cache.delete.assert_awaited_once()


class _FakeRedis:
    """Minimal in-memory Redis with yield points to expose async races.

    Every method awaits ``sleep(0)`` so concurrent callers actually
    interleave at the same await points the real client has.
    """

    def __init__(self) -> None:
        self.items: list[str] = []

    async def llen(self, key: str) -> int:
        await asyncio.sleep(0)
        return len(self.items)

    async def lpush(self, key: str, value: str) -> int:
        await asyncio.sleep(0)
        self.items.insert(0, value)
        return len(self.items)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        await asyncio.sleep(0)
        return self.items[start:] if stop == -1 else self.items[start:stop]

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        await asyncio.sleep(0)
        self.items[:] = self.items[start:] if stop == -1 else self.items[start : stop + 1]

    async def delete(self, key: str) -> int:
        await asyncio.sleep(0)
        n = len(self.items)
        self.items.clear()
        return n


class TestEnqueueBackpressureAtomicity:
    """OTHER#120: LLEN+LPUSH must not interleave between producers."""

    @pytest.mark.asyncio
    async def test_concurrent_producers_respect_max_queue_size(self):
        """并发 producer 不能突破 MAX_QUEUE_SIZE 软上限。"""
        fake = _FakeRedis()
        queue = ProcessingQueue(fake)

        def uuid_at(i: int) -> str:
            return f"550e8400-e29b-41d4-a716-{i:012d}"

        results = await asyncio.gather(*(queue.enqueue(uuid_at(i)) for i in range(300)))

        assert sum(results) == MAX_QUEUE_SIZE
        assert len(fake.items) == MAX_QUEUE_SIZE

    @pytest.mark.asyncio
    async def test_enqueue_under_limit_all_succeed(self):
        """低于上限时并发 enqueue 全部成功。"""
        fake = _FakeRedis()
        queue = ProcessingQueue(fake)

        results = await asyncio.gather(
            *(queue.enqueue(f"550e8400-e29b-41d4-a716-{i:012d}") for i in range(50))
        )

        assert all(results)
        assert len(fake.items) == 50


class TestDequeueBatchAtomicity:
    """OTHER#121: LRANGE+LTRIM must not double-dispatch to two consumers."""

    @pytest.mark.asyncio
    async def test_concurrent_consumers_no_duplicate_dispatch(self):
        """并发 dequeue_batch 不重复分发同一 article。"""
        fake = _FakeRedis()
        queue = ProcessingQueue(fake)
        for i in range(40):
            await queue.enqueue(f"550e8400-e29b-41d4-a716-{i:012d}")

        batches = await asyncio.gather(queue.dequeue_batch(15), queue.dequeue_batch(15))

        ids = [item[0] for batch in batches for item in batch]
        assert len(ids) == len(set(ids))  # no duplicates across consumers
        assert len(ids) == 30
        assert len(fake.items) == 10  # remainder intact

    @pytest.mark.asyncio
    async def test_dequeue_batch_preserves_producer_items(self):
        """消费期间 producer 的 LPUSH 不被 LTRIM 丢弃。"""
        fake = _FakeRedis()
        queue = ProcessingQueue(fake)
        for i in range(10):
            await queue.enqueue(f"550e8400-e29b-41d4-a716-{i:012d}")

        async def produce_late() -> None:
            await asyncio.sleep(0.01)
            await queue.enqueue("550e8400-e29b-41d4-a716-000000000abc")

        consume_task = queue.dequeue_batch(10)
        produce_task = asyncio.create_task(produce_late())
        consumed = await consume_task
        await produce_task

        assert len(consumed) == 10
        remaining_ids = [payload.split(":")[0] for payload in fake.items]
        # The late item must survive the trim (not be dropped by a stale
        # snapshot-based LTRIM/DEL).
        assert "550e8400-e29b-41d4-a716-000000000abc" in remaining_ids


class TestT008LowFixes:
    """Regression tests for T008 LOW findings (#262)."""

    @pytest.mark.asyncio
    async def test_invalid_uuid_message_is_truncated(self, queue):
        """#262: a huge malformed id must not be echoed verbatim into logs."""
        with pytest.raises(ValueError) as excinfo:
            await queue.enqueue("x" * 500)

        message = str(excinfo.value)
        assert "Invalid UUID format" in message
        assert len(message) < 120
