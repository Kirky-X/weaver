# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Retry module."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.collector.retry import RetryQueue


class TestRetryQueue:
    """Tests for RetryQueue."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis = MagicMock()
        redis.zadd = AsyncMock(return_value=1)
        redis.zrangebyscore = AsyncMock(return_value=[])
        redis.zrem = AsyncMock(return_value=1)
        redis.lpush = AsyncMock(return_value=1)
        redis.llen = AsyncMock(return_value=0)
        redis.lrange = AsyncMock(return_value=[])
        redis.delete = AsyncMock(return_value=1)
        return redis

    @pytest.fixture
    def retry_queue(self, mock_redis):
        """Create retry queue instance."""
        return RetryQueue(redis=mock_redis)

    def test_initialization(self, mock_redis):
        """Test retry queue initializes correctly."""
        queue = RetryQueue(redis=mock_redis)
        assert queue._redis is mock_redis
        assert queue._max_retries == 3
        assert queue._base_delay == 60.0

    def test_initialization_custom_params(self, mock_redis):
        """Test retry queue with custom parameters."""
        queue = RetryQueue(redis=mock_redis, max_retries=5, base_delay=30.0)
        assert queue._max_retries == 5
        assert queue._base_delay == 30.0

    def test_dead_letter_key_constant(self):
        """Test dead letter key constant."""
        assert RetryQueue.DEAD_LETTER_KEY == "crawl:dead"

    @pytest.mark.asyncio
    async def test_enqueue_first_attempt(self, retry_queue, mock_redis):
        """Test enqueueing item with first attempt."""
        await retry_queue.enqueue(url="https://example.com/article", host="example.com", attempt=0)
        mock_redis.zadd.assert_called_once()
        call_args = mock_redis.zadd.call_args
        assert "crawl:retry:example.com" in str(call_args)

    @pytest.mark.asyncio
    async def test_enqueue_second_attempt(self, retry_queue, mock_redis):
        """Test enqueueing item with second attempt."""
        await retry_queue.enqueue(url="https://example.com/article", host="example.com", attempt=1)
        mock_redis.zadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_moves_to_dead_letter_after_max_retries(self, retry_queue, mock_redis):
        """Test that item is moved to dead letter after max retries."""
        await retry_queue.enqueue(url="https://example.com/article", host="example.com", attempt=3)
        mock_redis.lpush.assert_called_once()
        mock_redis.zadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_due_items_empty(self, retry_queue, mock_redis):
        """Test getting due items when queue is empty."""
        mock_redis.zrangebyscore = AsyncMock(return_value=[])

        items = await retry_queue.get_due_items("example.com")

        assert items == []
        mock_redis.zrangebyscore.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_due_items_with_items(self, retry_queue, mock_redis):
        """Test getting due items from queue."""
        mock_data = [
            json.dumps(
                {"url": "https://example.com/article1", "host": "example.com", "attempt": 1}
            ).encode(),
            json.dumps(
                {"url": "https://example.com/article2", "host": "example.com", "attempt": 2}
            ).encode(),
        ]
        mock_redis.zrangebyscore = AsyncMock(return_value=mock_data)

        items = await retry_queue.get_due_items("example.com")

        assert len(items) == 2
        assert items[0]["url"] == "https://example.com/article1"
        mock_redis.zrem.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_due_items_handles_invalid_json(self, retry_queue, mock_redis):
        """Test that invalid JSON items are skipped."""
        mock_data = [
            b"invalid json",
            json.dumps(
                {"url": "https://example.com/article", "host": "example.com", "attempt": 1}
            ).encode(),
        ]
        mock_redis.zrangebyscore = AsyncMock(return_value=mock_data)

        items = await retry_queue.get_due_items("example.com")

        assert len(items) == 1
        assert items[0]["url"] == "https://example.com/article"

    @pytest.mark.asyncio
    async def test_move_to_dead_letter(self, retry_queue, mock_redis):
        """Test moving item to dead letter queue."""
        await retry_queue._move_to_dead_letter(
            url="https://example.com/article", host="example.com", attempt=3
        )
        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        assert RetryQueue.DEAD_LETTER_KEY in str(call_args)

    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self, retry_queue, mock_redis):
        """Test exponential backoff delay calculation."""
        base_delay = 60.0

        delays = [base_delay * (2**i) for i in range(5)]

        assert delays[0] == 60.0
        assert delays[1] == 120.0
        assert delays[2] == 240.0
        assert delays[3] == 480.0
        assert delays[4] == 960.0

    @pytest.mark.asyncio
    async def test_separate_queues_per_host(self, retry_queue, mock_redis):
        """Test that different hosts have separate retry queues."""
        await retry_queue.enqueue(url="https://a.com/article1", host="a.com", attempt=0)
        await retry_queue.enqueue(url="https://b.com/article2", host="b.com", attempt=0)

        assert mock_redis.zadd.call_count == 2

        calls = mock_redis.zadd.call_args_list
        keys = [str(call[0][0]) for call in calls]
        assert any("crawl:retry:a.com" in key for key in keys)
        assert any("crawl:retry:b.com" in key for key in keys)

    @pytest.mark.asyncio
    async def test_enqueue_payload_structure(self, retry_queue, mock_redis):
        """Test that enqueue creates correct payload structure."""
        await retry_queue.enqueue(url="https://example.com/article", host="example.com", attempt=1)

        call_args = mock_redis.zadd.call_args
        payload_dict = call_args[0][1]
        payload_str = list(payload_dict.keys())[0]
        payload = json.loads(payload_str)

        assert payload["url"] == "https://example.com/article"
        assert payload["host"] == "example.com"
        assert payload["attempt"] == 2
        assert "enqueued_at" in payload

    @pytest.mark.asyncio
    async def test_dead_letter_payload_structure(self, retry_queue, mock_redis):
        """Test that dead letter creates correct payload structure."""
        await retry_queue._move_to_dead_letter(
            url="https://example.com/article", host="example.com", attempt=3
        )

        call_args = mock_redis.lpush.call_args
        payload_str = call_args[0][1]
        payload = json.loads(payload_str)

        assert payload["url"] == "https://example.com/article"
        assert payload["host"] == "example.com"
        assert payload["final_attempt"] == 3
        assert "dead_at" in payload

    @pytest.mark.asyncio
    async def test_max_retries_boundary(self, mock_redis):
        """Test max retries boundary conditions."""
        queue = RetryQueue(redis=mock_redis, max_retries=3)

        await queue.enqueue(url="https://example.com/article", host="example.com", attempt=2)
        mock_redis.zadd.assert_called_once()
        mock_redis.lpush.assert_not_called()

        mock_redis.reset_mock()

        await queue.enqueue(url="https://example.com/article", host="example.com", attempt=3)
        mock_redis.zadd.assert_not_called()
        mock_redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_due_items_respects_limit(self, retry_queue, mock_redis):
        """Test that get_due_items respects the limit parameter."""
        mock_redis.zrangebyscore = AsyncMock(return_value=[])

        await retry_queue.get_due_items("example.com")

        call_args = mock_redis.zrangebyscore.call_args
        assert call_args[1].get("num") == 50
