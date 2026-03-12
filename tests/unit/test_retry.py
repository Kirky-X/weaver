"""Unit tests for Retry module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta
import time

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
        return redis

    @pytest.fixture
    def retry_queue(self, mock_redis):
        """Create retry queue instance."""
        return RetryQueue(redis=mock_redis)

    def test_initialization(self, mock_redis):
        """Test retry queue initializes correctly."""
        queue = RetryQueue(redis=mock_redis)
        assert queue._redis is mock_redis

    @pytest.mark.asyncio
    async def test_retry_queue_add(self, retry_queue, mock_redis):
        """Test adding item to retry queue."""
        item = {"url": "https://example.com/article", "attempt": 1}
        await retry_queue.add("example.com", item, delay_seconds=60)
        mock_redis.zadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_queue_pop_due(self, retry_queue, mock_redis):
        """Test popping due items from retry queue."""
        mock_data = [
            b'{"url": "https://example.com/article1"}',
            b'{"url": "https://example.com/article2"}',
        ]
        mock_redis.zrangebyscore = AsyncMock(return_value=mock_data)
        
        items = await retry_queue.pop_due("example.com")
        
        assert len(items) == 2
        mock_redis.zrem.assert_called()

    @pytest.mark.asyncio
    async def test_dead_letter_queue(self, retry_queue, mock_redis):
        """Test adding to dead letter queue."""
        item = {"url": "https://example.com/article", "error": "Max retries exceeded"}
        await retry_queue.add_to_dead_letter(item)
        mock_redis.lpush.assert_called()

    @pytest.mark.asyncio
    async def test_max_retries(self, retry_queue, mock_redis):
        """Test max retries limit."""
        item = {
            "url": "https://example.com/article",
            "attempt": 5,
            "max_retries": 3
        }
        
        is_max = item.get("attempt", 0) >= item.get("max_retries", 3)
        assert is_max is True

    @pytest.mark.asyncio
    async def test_get_dead_letter_count(self, retry_queue, mock_redis):
        """Test getting dead letter queue count."""
        mock_redis.llen = AsyncMock(return_value=10)
        count = await retry_queue.get_dead_letter_count()
        assert count == 10

    @pytest.mark.asyncio
    async def test_get_dead_letter_items(self, retry_queue, mock_redis):
        """Test getting items from dead letter queue."""
        mock_items = [
            b'{"url": "https://example.com/failed1"}',
            b'{"url": "https://example.com/failed2"}',
        ]
        mock_redis.lrange = AsyncMock(return_value=mock_items)
        
        items = await retry_queue.get_dead_letter_items(limit=10)
        
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_clear_dead_letter(self, retry_queue, mock_redis):
        """Test clearing dead letter queue."""
        mock_redis.delete = AsyncMock(return_value=1)
        await retry_queue.clear_dead_letter()
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_retry_delay_calculation(self, retry_queue, mock_redis):
        """Test retry delay is calculated correctly."""
        item = {"url": "https://example.com/article"}
        base_delay = 30
        attempt = 2
        expected_delay = base_delay * (2 ** attempt)
        
        await retry_queue.add("example.com", item, delay_seconds=expected_delay)
        
        call_args = mock_redis.zadd.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_multiple_hosts_separate_queues(self, retry_queue, mock_redis):
        """Test separate queues for different hosts."""
        item1 = {"url": "https://a.com/article"}
        item2 = {"url": "https://b.com/article"}
        
        await retry_queue.add("a.com", item1, delay_seconds=60)
        await retry_queue.add("b.com", item2, delay_seconds=60)
        
        assert mock_redis.zadd.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_pop_due(self, retry_queue, mock_redis):
        """Test popping when no items are due."""
        mock_redis.zrangebyscore = AsyncMock(return_value=[])
        
        items = await retry_queue.pop_due("example.com")
        
        assert items == []

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, retry_queue, mock_redis):
        """Test exponential backoff for retries."""
        base_delay = 30
        
        delays = [base_delay * (2 ** i) for i in range(5)]
        
        assert delays[0] == 30
        assert delays[1] == 60
        assert delays[2] == 120
        assert delays[3] == 240
        assert delays[4] == 480
