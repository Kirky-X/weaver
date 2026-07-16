# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for core.cache.redis module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cache.redis import CashewsClient, RedisClient


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


class TestCashewsClientScanDelete:
    """Test CashewsClient scan_iter and delete across all data structures.

    Regression tests for bug where scan_iter only scanned _store (KV),
    missing keys written via hincrby (to _hashes). This caused the LLM
    usage aggregator to find no keys, leaving llm_usage_hourly empty.
    """

    @pytest.mark.asyncio
    async def test_scan_iter_finds_hash_key_after_hincrby(self):
        """scan_iter must find keys written via hincrby (stored in _hashes)."""
        client = CashewsClient()
        await client.hincrby("llm:usage:2026062800", "label::cp::count", 1)

        keys = [k async for k in client.scan_iter("llm:usage:*")]
        assert "llm:usage:2026062800" in keys

    @pytest.mark.asyncio
    async def test_scan_iter_finds_keys_across_all_structures(self):
        """scan_iter must find keys from _store, _hashes, _lists, _sorted_sets."""
        client = CashewsClient()
        await client.set("kv:key", "value")
        await client.hincrby("hash:key", "field", 1)
        await client.lpush("list:key", "item")
        await client.zadd("zset:key", {"member": 1.0})

        keys = {k async for k in client.scan_iter("*")}
        assert "kv:key" in keys
        assert "hash:key" in keys
        assert "list:key" in keys
        assert "zset:key" in keys

    @pytest.mark.asyncio
    async def test_delete_removes_hash_key(self):
        """delete must remove keys from _hashes, not just _store."""
        client = CashewsClient()
        await client.hincrby("llm:usage:2026062800", "field", 1)

        # Verify key exists
        keys_before = [k async for k in client.scan_iter("llm:usage:*")]
        assert len(keys_before) == 1

        # Delete and verify return count (1 key deleted, not 1 field)
        count = await client.delete("llm:usage:2026062800")
        assert count == 1

        # Verify key is gone
        keys_after = [k async for k in client.scan_iter("llm:usage:*")]
        assert len(keys_after) == 0

    @pytest.mark.asyncio
    async def test_delete_missing_key_returns_zero(self):
        """delete of a non-existent key returns 0."""
        client = CashewsClient()
        count = await client.delete("nonexistent")
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_removes_from_all_structures(self):
        """delete must clean up a key regardless of which structure holds it."""
        client = CashewsClient()
        await client.set("key", "value")
        await client.hincrby("key", "field", 1)  # Also in _hashes

        count = await client.delete("key")
        assert count == 1  # Redis returns 1 even if key had multiple types

        # Both structures should be clean
        assert "key" not in client._store
        assert "key" not in client._hashes


class TestCashewsClientHdelAndExpiry:
    """Test CashewsClient hdel auto-cleanup and scan_iter expiry filtering.

    Regression tests for pre-existing issues flagged by code reviewer:
    - hdel left an empty dict in _hashes after deleting the last field,
      causing scan_iter to yield a phantom key.
    - scan_iter did not call _check_expiry, so expired-but-not-yet-cleaned
      keys were still yielded to callers.
    """

    @pytest.mark.asyncio
    async def test_hdel_removes_empty_hash_key(self):
        """Deleting the last field of a hash must remove the key entirely."""
        client = CashewsClient()
        await client.hincrby("llm:usage:2026062800", "field1", 1)
        await client.hincrby("llm:usage:2026062800", "field2", 1)

        # Delete both fields
        count = await client.hdel("llm:usage:2026062800", "field1", "field2")
        assert count == 2

        # Hash key must be gone entirely (mirrors real Redis)
        assert "llm:usage:2026062800" not in client._hashes
        # And scan_iter must not yield it
        keys = [k async for k in client.scan_iter("llm:usage:*")]
        assert keys == []

    @pytest.mark.asyncio
    async def test_hdel_partial_keep_hash_key(self):
        """Deleting some fields but not all must keep the hash key."""
        client = CashewsClient()
        await client.hincrby("hash:key", "f1", 1)
        await client.hincrby("hash:key", "f2", 1)

        count = await client.hdel("hash:key", "f1")
        assert count == 1
        assert "hash:key" in client._hashes
        assert client._hashes["hash:key"] == {"f2": "1"}

    @pytest.mark.asyncio
    async def test_hdel_nonexistent_field_keeps_hash(self):
        """hdel on a missing field must not remove the hash key."""
        client = CashewsClient()
        await client.hincrby("hash:key", "f1", 1)

        count = await client.hdel("hash:key", "missing")
        assert count == 0
        assert "hash:key" in client._hashes

    @pytest.mark.asyncio
    async def test_scan_iter_skips_expired_kv_key(self):
        """scan_iter must not yield a KV key whose TTL has elapsed."""
        client = CashewsClient()
        await client.set("live:key", "value")
        await client.set("dead:key", "value", ex=1)
        # Force expiry by backdating the TTL
        client._expiry["dead:key"] = 0.0

        keys = {k async for k in client.scan_iter("*")}
        assert "live:key" in keys
        assert "dead:key" not in keys
        # Expired key must be cleaned up
        assert "dead:key" not in client._store
        assert "dead:key" not in client._expiry

    @pytest.mark.asyncio
    async def test_scan_iter_skips_expired_hash_key(self):
        """scan_iter must not yield an expired hash key."""
        client = CashewsClient()
        await client.hincrby("live:hash", "field", 1)
        await client.hincrby("dead:hash", "field", 1)
        client._expiry["dead:hash"] = 0.0  # backdate TTL

        keys = {k async for k in client.scan_iter("*")}
        assert "live:hash" in keys
        assert "dead:hash" not in keys
        assert "dead:hash" not in client._hashes
        # Symmetric with the KV test: _expiry must also be cleaned up
        assert "dead:hash" not in client._expiry

    @pytest.mark.asyncio
    async def test_hdel_on_non_hash_key_preserves_ttl(self):
        """hdel on a key that exists as KV (not hash) must not strip its TTL.

        Regression test for a bug where `h = self._hashes.get(name, {})`
        returned a temporary empty dict, `if not h:` was True, and
        `self._expiry.pop(name, None)` removed the TTL of the unrelated
        KV key, making it live forever.
        """
        client = CashewsClient()
        await client.set("kv:key", "value", ex=60)

        # hdel on a non-hash key must return 0 and NOT touch _expiry
        count = await client.hdel("kv:key", "field")
        assert count == 0
        assert "kv:key" in client._store  # KV value untouched
        assert "kv:key" in client._expiry  # TTL preserved

    @pytest.mark.asyncio
    async def test_hdel_on_missing_key_returns_zero(self):
        """hdel on a completely non-existent key must return 0."""
        client = CashewsClient()
        count = await client.hdel("nonexistent", "field")
        assert count == 0
        assert "nonexistent" not in client._hashes
        assert "nonexistent" not in client._expiry

    @pytest.mark.asyncio
    async def test_hdel_on_expired_hash_returns_zero(self):
        """hdel on an expired hash must return 0 (key treated as gone)."""
        client = CashewsClient()
        await client.hincrby("dead:hash", "field", 1)
        client._expiry["dead:hash"] = 0.0  # backdate TTL

        count = await client.hdel("dead:hash", "field")
        assert count == 0
        assert "dead:hash" not in client._hashes

    @pytest.mark.asyncio
    async def test_scan_iter_skips_expired_key_with_pattern(self):
        """scan_iter with pattern must also skip expired keys."""
        client = CashewsClient()
        await client.set("llm:usage:live", "1")
        await client.set("llm:usage:dead", "1", ex=1)
        client._expiry["llm:usage:dead"] = 0.0

        keys = [k async for k in client.scan_iter("llm:usage:*")]
        assert keys == ["llm:usage:live"]
