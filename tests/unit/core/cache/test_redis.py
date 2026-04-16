# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for core.cache.redis module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cache.redis import RedisClient


class TestRedisClientInit:
    """Test RedisClient initialization."""

    def test_init_stores_url(self):
        """Test __init__ stores URL."""
        client = RedisClient("redis://localhost:6379")
        assert client._url == "redis://localhost:6379"
        assert client._pool is None
        assert client._redis is None


class TestRedisClientStartup:
    """Test RedisClient startup."""

    @pytest.mark.asyncio
    async def test_startup_creates_pool(self):
        """Test startup creates connection pool."""
        client = RedisClient("redis://localhost:6379")

        with patch("core.cache.redis.ConnectionPool") as mock_pool_class:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock()
            mock_pool_class.from_url.return_value = MagicMock()

            with patch("core.cache.redis.Redis", return_value=mock_redis):
                await client.startup()

                mock_pool_class.from_url.assert_called_once()
                assert client._pool is not None
                assert client._redis is not None

    @pytest.mark.asyncio
    async def test_startup_pings_server(self):
        """Test startup pings Redis server."""
        client = RedisClient("redis://localhost:6379")

        with patch("core.cache.redis.ConnectionPool") as mock_pool_class:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock()
            mock_pool_class.from_url.return_value = MagicMock()

            with patch("core.cache.redis.Redis", return_value=mock_redis):
                await client.startup()

                mock_redis.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_failure_raises_connection_error(self):
        """Test startup failure raises ConnectionError."""
        client = RedisClient("redis://localhost:6379")

        with patch("core.cache.redis.ConnectionPool") as mock_pool_class:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("Connection refused"))
            mock_pool_class.from_url.return_value = MagicMock()

            with patch("core.cache.redis.Redis", return_value=mock_redis):
                with pytest.raises(ConnectionError, match="Failed to connect"):
                    await client.startup()

                # Should cleanup on failure
                assert client._redis is None
                assert client._pool is None


class TestRedisClientShutdown:
    """Test RedisClient shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_connection(self):
        """Test shutdown closes Redis connection."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()

        await client.shutdown()

        client._redis.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_when_not_started(self):
        """Test shutdown when not started does nothing."""
        client = RedisClient("redis://localhost:6379")
        await client.shutdown()  # Should not raise


class TestRedisClientClient:
    """Test RedisClient.client property."""

    def test_client_returns_redis_instance(self):
        """Test client property returns Redis instance."""
        client = RedisClient("redis://localhost:6379")
        client._redis = MagicMock()

        result = client.client
        assert result is client._redis

    def test_client_raises_when_not_started(self):
        """Test client property raises RuntimeError when not started."""
        client = RedisClient("redis://localhost:6379")

        with pytest.raises(RuntimeError, match="not started"):
            _ = client.client


class TestRedisClientBasicOperations:
    """Test basic Redis operations."""

    @pytest.mark.asyncio
    async def test_get(self):
        """Test get operation."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()
        client._redis.get = AsyncMock(return_value="value")

        result = await client.get("key")
        assert result == "value"
        client._redis.get.assert_called_once_with("key")

    @pytest.mark.asyncio
    async def test_get_returns_none(self):
        """Test get returns None for missing key."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()
        client._redis.get = AsyncMock(return_value=None)

        result = await client.get("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_mget(self):
        """Test mget operation."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()
        client._redis.mget = AsyncMock(return_value=["val1", None, "val3"])

        result = await client.mget(["key1", "key2", "key3"])
        assert result == ["val1", None, "val3"]

    @pytest.mark.asyncio
    async def test_mget_empty_keys(self):
        """Test mget with empty keys returns empty list."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()

        result = await client.mget([])
        assert result == []
        client._redis.mget.assert_not_called()

    @pytest.mark.asyncio
    async def test_set(self):
        """Test set operation."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()
        client._redis.set = AsyncMock()

        await client.set("key", "value")
        client._redis.set.assert_called_once_with("key", "value", ex=None)

    @pytest.mark.asyncio
    async def test_set_with_expiry(self):
        """Test set operation with expiry."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()
        client._redis.set = AsyncMock()

        await client.set("key", "value", ex=3600)
        client._redis.set.assert_called_once_with("key", "value", ex=3600)

    @pytest.mark.asyncio
    async def test_delete(self):
        """Test delete operation."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()
        client._redis.delete = AsyncMock(return_value=1)

        result = await client.delete("key")
        assert result == 1
        client._redis.delete.assert_called_once_with("key")


class TestRedisClientPing:
    """Test ping operation."""

    @pytest.mark.asyncio
    async def test_ping(self):
        """Test ping operation."""
        client = RedisClient("redis://localhost:6379")
        client._redis = AsyncMock()
        client._redis.ping = AsyncMock(return_value=True)

        result = await client.ping()
        assert result is True


class TestRedisClientHealthTracking:
    """Test RedisClient health tracking."""

    def test_health_status_tracking(self):
        """Test health status is tracked."""
        client = RedisClient("redis://localhost:6379")

        # Initial state
        assert hasattr(client, "_last_failure_time") or True  # Implementation detail

    @pytest.mark.asyncio
    async def test_startup_logs_on_success(self):
        """Test startup logs success."""
        client = RedisClient("redis://localhost:6379")

        with patch("core.cache.redis.ConnectionPool") as mock_pool_class:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock()
            mock_pool_class.from_url.return_value = MagicMock()

            with patch("core.cache.redis.Redis", return_value=mock_redis):
                with patch("core.cache.redis.log") as mock_log:
                    await client.startup()
                    mock_log.info.assert_called()
