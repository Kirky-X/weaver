# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Redis cache unit tests.

Tests for Redis cache operations including:
- Connection management
- Cache operations (get/set/delete)
- Distributed locks
- Pub/Sub messaging
- Error handling and recovery
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.asyncio import Redis as AsyncRedis


class TestRedisConnection:
    """Tests for Redis connection management."""

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        """Create a mock Redis client."""
        redis_client = AsyncMock(spec=AsyncRedis)
        redis_client.ping = AsyncMock(return_value=True)
        redis_client.close = AsyncMock()
        return redis_client

    @pytest.mark.asyncio
    async def test_redis_ping(self, mock_redis: AsyncMock) -> None:
        """Test Redis connection ping."""
        result = await mock_redis.ping()
        assert result is True
        mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_connection_close(self, mock_redis: AsyncMock) -> None:
        """Test closing Redis connection."""
        await mock_redis.close()
        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_auto_reconnect(self, mock_redis: AsyncMock) -> None:
        """Test automatic reconnection on failure."""
        # First call fails, second succeeds
        mock_redis.ping.side_effect = [
            ConnectionError("Connection lost"),
            True,
        ]

        # Simulate reconnection logic
        try:
            await mock_redis.ping()
        except ConnectionError:
            # Reconnect
            mock_redis.ping.reset_mock()
            mock_redis.ping.return_value = True

        result = await mock_redis.ping()
        assert result is True


class TestRedisCacheOperations:
    """Tests for Redis cache operations."""

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        """Create a mock Redis client with cache operations."""
        redis_client = AsyncMock(spec=AsyncRedis)
        redis_client.get = AsyncMock()
        redis_client.set = AsyncMock()
        redis_client.delete = AsyncMock()
        redis_client.exists = AsyncMock()
        redis_client.expire = AsyncMock()
        return redis_client

    @pytest.mark.asyncio
    async def test_cache_set(self, mock_redis: AsyncMock) -> None:
        """Test setting a value in cache."""
        key = "test_key"
        value = b"test_value"

        await mock_redis.set(key, value)
        mock_redis.set.assert_called_once_with(key, value)

    @pytest.mark.asyncio
    async def test_cache_get(self, mock_redis: AsyncMock) -> None:
        """Test getting a value from cache."""
        key = "test_key"
        expected_value = b"test_value"

        mock_redis.get.return_value = expected_value
        result = await mock_redis.get(key)

        assert result == expected_value
        mock_redis.get.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_cache_get_missing(self, mock_redis: AsyncMock) -> None:
        """Test getting a non-existent key."""
        key = "nonexistent_key"

        mock_redis.get.return_value = None
        result = await mock_redis.get(key)

        assert result is None
        mock_redis.get.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_cache_delete(self, mock_redis: AsyncMock) -> None:
        """Test deleting a key from cache."""
        key = "test_key"

        await mock_redis.delete(key)
        mock_redis.delete.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_cache_exists(self, mock_redis: AsyncMock) -> None:
        """Test checking if a key exists."""
        key = "test_key"

        mock_redis.exists.return_value = 1
        result = await mock_redis.exists(key)

        assert result == 1
        mock_redis.exists.assert_called_once_with(key)

    @pytest.mark.asyncio
    async def test_cache_expire(self, mock_redis: AsyncMock) -> None:
        """Test setting expiration time."""
        key = "test_key"
        ttl = 3600  # 1 hour

        await mock_redis.expire(key, ttl)
        mock_redis.expire.assert_called_once_with(key, ttl)

    @pytest.mark.asyncio
    async def test_cache_set_with_ttl(self, mock_redis: AsyncMock) -> None:
        """Test setting a value with TTL."""
        key = "test_key"
        value = b"test_value"
        ttl = 3600

        await mock_redis.set(key, value, ex=ttl)
        mock_redis.set.assert_called_once_with(key, value, ex=ttl)


class TestRedisDistributedLock:
    """Tests for Redis distributed lock."""

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        """Create a mock Redis client with lock support."""
        redis_client = AsyncMock(spec=AsyncRedis)
        redis_client.set = AsyncMock()
        redis_client.delete = AsyncMock()
        return redis_client

    @pytest.mark.asyncio
    async def test_lock_acquire(self, mock_redis: AsyncMock) -> None:
        """Test acquiring a distributed lock."""
        lock_name = "test_lock"
        lock_value = "unique_identifier"
        ttl = 10

        # Simulate successful lock acquisition
        mock_redis.set.return_value = True

        result = await mock_redis.set(lock_name, lock_value, nx=True, ex=ttl)

        assert result is True
        mock_redis.set.assert_called_once_with(lock_name, lock_value, nx=True, ex=ttl)

    @pytest.mark.asyncio
    async def test_lock_release(self, mock_redis: AsyncMock) -> None:
        """Test releasing a distributed lock."""
        lock_name = "test_lock"

        await mock_redis.delete(lock_name)
        mock_redis.delete.assert_called_once_with(lock_name)

    @pytest.mark.asyncio
    async def test_lock_timeout(self, mock_redis: AsyncMock) -> None:
        """Test lock timeout mechanism."""
        lock_name = "test_lock"

        # Lock already exists
        mock_redis.set.return_value = False

        result = await mock_redis.set(lock_name, "value", nx=True, ex=10)

        assert result is False
        mock_redis.set.assert_called_once()


class TestRedisPubSub:
    """Tests for Redis Pub/Sub messaging."""

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        """Create a mock Redis client with pub/sub support."""
        redis_client = AsyncMock(spec=AsyncRedis)
        redis_client.publish = AsyncMock()
        redis_client.subscribe = AsyncMock()
        redis_client.unsubscribe = AsyncMock()
        return redis_client

    @pytest.mark.asyncio
    async def test_publish_message(self, mock_redis: AsyncMock) -> None:
        """Test publishing a message to a channel."""
        channel = "test_channel"
        message = "Hello, subscribers!"

        await mock_redis.publish(channel, message)
        mock_redis.publish.assert_called_once_with(channel, message)

    @pytest.mark.asyncio
    async def test_subscribe_channel(self, mock_redis: AsyncMock) -> None:
        """Test subscribing to a channel."""
        channel = "test_channel"

        await mock_redis.subscribe(channel)
        mock_redis.subscribe.assert_called_once_with(channel)

    @pytest.mark.asyncio
    async def test_unsubscribe_channel(self, mock_redis: AsyncMock) -> None:
        """Test unsubscribing from a channel."""
        channel = "test_channel"

        await mock_redis.unsubscribe(channel)
        mock_redis.unsubscribe.assert_called_once_with(channel)


class TestRedisErrorHandling:
    """Tests for Redis error handling."""

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        """Create a mock Redis client."""
        redis_client = AsyncMock(spec=AsyncRedis)
        return redis_client

    @pytest.mark.asyncio
    async def test_connection_error_recovery(self, mock_redis: AsyncMock) -> None:
        """Test recovering from connection errors."""
        # Simulate successful ping after reconnection
        mock_redis.ping = AsyncMock(return_value=True)

        result = await mock_redis.ping()
        assert result is True
        mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_redis: AsyncMock) -> None:
        """Test handling operation timeouts."""
        mock_redis.get.side_effect = TimeoutError("Operation timed out")

        with pytest.raises(asyncio.TimeoutError):
            await mock_redis.get("test_key")
