# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for RetryQueue (ingestion deduplication module)."""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from loguru import logger

from core.constants import RedisKeys
from modules.ingestion.deduplication.retry import RetryQueue


class TestRetryQueueInit:
    """Tests for RetryQueue initialization."""

    def test_retry_queue_initialization(self):
        """Test retry queue initializes correctly."""
        mock_cache = MagicMock()

        retry_queue = RetryQueue(cache=mock_cache)

        assert retry_queue._cache is mock_cache
        assert retry_queue._max_retries == 3
        assert retry_queue._base_delay == 60.0
        assert retry_queue.DEAD_LETTER_KEY == RedisKeys.CRAWL_DEAD_LETTER

    def test_retry_queue_with_custom_params(self):
        """Test retry queue with custom parameters."""
        mock_cache = MagicMock()

        retry_queue = RetryQueue(
            cache=mock_cache,
            max_retries=5,
            base_delay=120.0,
        )

        assert retry_queue._max_retries == 5
        assert retry_queue._base_delay == 120.0


class TestRetryQueueEnqueue:
    """Tests for RetryQueue.enqueue method."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.zadd = AsyncMock()
        cache.lpush = AsyncMock()
        cache.ltrim = AsyncMock()
        return cache

    @pytest.mark.asyncio
    async def test_enqueue_first_attempt(self, mock_cache):
        """Test enqueue with first attempt."""
        retry_queue = RetryQueue(cache=mock_cache)

        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=0,
        )

        # Should add to retry queue (not dead letter)
        mock_cache.zadd.assert_called_once()
        mock_cache.lpush.assert_not_called()

        # Check key format
        call_args = mock_cache.zadd.call_args
        expected_key = RedisKeys.crawl_retry("example.com")
        assert call_args[0][0] == expected_key

    @pytest.mark.asyncio
    async def test_enqueue_exponential_backoff(self, mock_cache):
        """Test exponential backoff delay calculation."""
        retry_queue = RetryQueue(cache=mock_cache, base_delay=60.0)

        # Attempt 0: delay = 60 * 2^0 = 60 seconds
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=0,
        )

        call_args = mock_cache.zadd.call_args
        score = list(call_args[0][1].values())[0]
        # Score should be current time + delay
        assert score > time.time()
        assert score < time.time() + 120  # Within reasonable range

        # Attempt 1: delay = 60 * 2^1 = 120 seconds
        mock_cache.zadd.reset_mock()
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=1,
        )

        call_args = mock_cache.zadd.call_args
        score = list(call_args[0][1].values())[0]
        # Should have larger delay
        assert score > time.time() + 60

    @pytest.mark.asyncio
    async def test_enqueue_payload_format(self, mock_cache):
        """Test payload format contains correct fields."""
        retry_queue = RetryQueue(cache=mock_cache)

        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=2,
        )

        call_args = mock_cache.zadd.call_args
        payload_str = list(call_args[0][1].keys())[0]
        payload = json.loads(payload_str)

        assert payload["url"] == "https://example.com/article"
        assert payload["host"] == "example.com"
        assert payload["attempt"] == 3  # attempt + 1
        assert "enqueued_at" in payload

    @pytest.mark.asyncio
    async def test_enqueue_moves_to_dead_letter_when_max_retries_exceeded(self, mock_cache):
        """Test moves to dead letter when max retries exceeded."""
        retry_queue = RetryQueue(cache=mock_cache, max_retries=3)

        # Attempt 3 equals max_retries, should go to dead letter
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=3,
        )

        mock_cache.zadd.assert_not_called()
        mock_cache.lpush.assert_called_once()

        call_args = mock_cache.lpush.call_args
        assert call_args[0][0] == RetryQueue.DEAD_LETTER_KEY

        payload_str = call_args[0][1]
        payload = json.loads(payload_str)

        assert payload["url"] == "https://example.com/article"
        assert payload["host"] == "example.com"
        assert payload["final_attempt"] == 3
        assert "dead_at" in payload

    @pytest.mark.asyncio
    async def test_enqueue_moves_to_dead_letter_after_max(self, mock_cache):
        """Test moves to dead letter when attempt exceeds max retries."""
        retry_queue = RetryQueue(cache=mock_cache, max_retries=3)

        # Attempt 4 exceeds max_retries
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=4,
        )

        mock_cache.zadd.assert_not_called()
        mock_cache.lpush.assert_called_once()


class TestRetryQueueGetDueItems:
    """Tests for RetryQueue.get_due_items method."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.zrangebyscore = AsyncMock()
        # zrem must return the number of members actually removed (int) —
        # get_due_items compares it against the fetched count to surface
        # concurrent claims.
        cache.zrem = AsyncMock(side_effect=lambda key, *members: len(members))
        return cache

    @pytest.mark.asyncio
    async def test_get_due_items_no_items(self, mock_cache):
        """Test get_due_items with no items due."""
        mock_cache.zrangebyscore = AsyncMock(return_value=[])

        retry_queue = RetryQueue(cache=mock_cache)

        result = await retry_queue.get_due_items("example.com")

        assert result == []
        mock_cache.zrem.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_due_items_with_items(self, mock_cache):
        """Test get_due_items with due items."""
        items = [
            json.dumps({"url": "https://example.com/1", "host": "example.com", "attempt": 1}),
            json.dumps({"url": "https://example.com/2", "host": "example.com", "attempt": 2}),
        ]
        mock_cache.zrangebyscore = AsyncMock(return_value=items)

        retry_queue = RetryQueue(cache=mock_cache)

        result = await retry_queue.get_due_items("example.com")

        assert len(result) == 2
        assert result[0]["url"] == "https://example.com/1"
        assert result[1]["url"] == "https://example.com/2"

        # Should remove fetched items
        mock_cache.zrem.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_due_items_removes_from_queue(self, mock_cache):
        """Test get_due_items removes fetched items."""
        items = [
            json.dumps({"url": "https://example.com/1", "host": "example.com", "attempt": 1}),
        ]
        mock_cache.zrangebyscore = AsyncMock(return_value=items)

        retry_queue = RetryQueue(cache=mock_cache)

        await retry_queue.get_due_items("example.com")

        # Verify zrem was called with the items
        call_args = mock_cache.zrem.call_args
        expected_key = RedisKeys.crawl_retry("example.com")
        assert call_args[0][0] == expected_key

    @pytest.mark.asyncio
    async def test_get_due_items_handles_invalid_json(self, mock_cache):
        """Test get_due_items handles invalid JSON gracefully."""
        items = [
            "invalid_json_string",
            json.dumps({"url": "https://example.com/valid", "host": "example.com", "attempt": 1}),
        ]
        mock_cache.zrangebyscore = AsyncMock(return_value=items)

        retry_queue = RetryQueue(cache=mock_cache)

        result = await retry_queue.get_due_items("example.com")

        # Should only return valid JSON items
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/valid"

    @pytest.mark.asyncio
    async def test_get_due_items_limits_results(self, mock_cache):
        """Test get_due_items limits results to 50."""
        retry_queue = RetryQueue(cache=mock_cache)

        await retry_queue.get_due_items("example.com")

        call_args = mock_cache.zrangebyscore.call_args
        assert call_args[1]["num"] == 50


class TestRetryQueueMoveToDeadLetter:
    """Tests for RetryQueue._move_to_dead_letter method."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.lpush = AsyncMock()
        cache.ltrim = AsyncMock()
        return cache

    @pytest.mark.asyncio
    async def test_move_to_dead_letter_format(self, mock_cache):
        """Test dead letter payload format."""
        retry_queue = RetryQueue(cache=mock_cache)

        await retry_queue._move_to_dead_letter(
            url="https://example.com/article",
            host="example.com",
            attempt=5,
        )

        call_args = mock_cache.lpush.call_args
        payload_str = call_args[0][1]
        payload = json.loads(payload_str)

        assert payload["url"] == "https://example.com/article"
        assert payload["host"] == "example.com"
        assert payload["final_attempt"] == 5
        assert "dead_at" in payload


class TestRetryQueueIntegration:
    """Integration-like tests for retry flow."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.zadd = AsyncMock()
        cache.lpush = AsyncMock()
        cache.ltrim = AsyncMock()
        cache.zrangebyscore = AsyncMock(return_value=[])
        cache.zrem = AsyncMock()
        return cache

    @pytest.mark.asyncio
    async def test_full_retry_cycle(self, mock_cache):
        """Test a full retry cycle from enqueue to dead letter."""
        retry_queue = RetryQueue(cache=mock_cache, max_retries=3)

        # First enqueue (attempt 0)
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=0,
        )
        assert mock_cache.zadd.call_count == 1
        assert mock_cache.lpush.call_count == 0

        # Second enqueue (attempt 1)
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=1,
        )
        assert mock_cache.zadd.call_count == 2

        # Third enqueue (attempt 2)
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=2,
        )
        assert mock_cache.zadd.call_count == 3

        # Fourth enqueue (attempt 3 - max exceeded)
        await retry_queue.enqueue(
            url="https://example.com/article",
            host="example.com",
            attempt=3,
        )
        assert mock_cache.zadd.call_count == 3  # No new zadd
        assert mock_cache.lpush.call_count == 1  # Moved to dead letter


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client returning payloads without claiming them."""
        cache = MagicMock()
        cache.zrangebyscore = AsyncMock()
        cache.zrem = AsyncMock(side_effect=lambda key, *members: len(members))
        return cache

    @staticmethod
    def _capture(records: list) -> int:
        return logger.add(lambda message: records.append(message.record), level="DEBUG")

    @pytest.mark.asyncio
    async def test_payload_host_mismatch_is_flagged(self, mock_cache):
        """#175: payload host disagreeing with the set's host is logged."""
        mock_cache.zrangebyscore = AsyncMock(
            return_value=[json.dumps({"url": "https://other.com/1", "host": "other.com"})]
        )
        records: list = []
        sink_id = self._capture(records)
        try:
            retry_queue = RetryQueue(cache=mock_cache)
            result = await retry_queue.get_due_items("example.com")
        finally:
            logger.remove(sink_id)

        # The item is still returned, but the corruption is surfaced.
        assert len(result) == 1
        mismatches = [r for r in records if r["message"] == "retry_item_host_mismatch"]
        assert mismatches, "expected retry_item_host_mismatch to be logged"
        assert mismatches[0]["extra"]["expected_host"] == "example.com"
        assert mismatches[0]["extra"]["item_host"] == "other.com"

    @pytest.mark.asyncio
    async def test_matching_payload_host_is_not_flagged(self, mock_cache):
        """#175: the happy path stays silent."""
        mock_cache.zrangebyscore = AsyncMock(
            return_value=[json.dumps({"url": "https://example.com/1", "host": "example.com"})]
        )
        records: list = []
        sink_id = self._capture(records)
        try:
            retry_queue = RetryQueue(cache=mock_cache)
            result = await retry_queue.get_due_items("example.com")
        finally:
            logger.remove(sink_id)

        assert len(result) == 1
        assert not [r for r in records if r["message"] == "retry_item_host_mismatch"]


class TestT008LowFixes:
    """Regression tests for LOW findings."""

    @pytest.mark.asyncio
    async def test_host_mismatch_is_logged(self):
        """#175: a payload host that disagrees with the set's host is flagged."""
        import modules.ingestion.deduplication.retry as retry_module
        from modules.ingestion.deduplication.retry import RetryQueue

        cache = AsyncMock()
        payload = '{"url": "https://a.example.com/x", "host": "other.example.com", "attempt": 0}'
        cache.zrangebyscore = AsyncMock(return_value=[payload])
        cache.zrem = AsyncMock(return_value=1)
        queue = RetryQueue(cache=cache)

        warnings: list = []

        class _Sink:
            def warning(self, event, **kwargs):
                warnings.append((event, kwargs))

        original = retry_module.log
        retry_module.log = _Sink()
        try:
            due = await queue.get_due_items("a.example.com")
        finally:
            retry_module.log = original

        assert due, "the item should still be returned"
        assert any(event == "retry_item_host_mismatch" for event, _ in warnings)
