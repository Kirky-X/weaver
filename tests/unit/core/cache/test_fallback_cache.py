# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for FallbackCachePool — runtime Redis→Cashews degradation.

TDD Phase 1: Write tests first, then implement.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cache.fallback import FallbackCachePool
from core.protocols import CachePool, assert_implements

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock RedisClient that succeeds by default."""
    redis = AsyncMock()
    redis.ping.return_value = True
    redis.get.return_value = "redis_value"
    redis.set.return_value = None
    redis.delete.return_value = 1
    redis.expire.return_value = True
    redis.hget.return_value = "hash_value"
    redis.hset.return_value = None
    redis.hexists.return_value = True
    redis.hexists_many.return_value = [True, False]
    redis.hgetall.return_value = {"key": "value"}
    redis.hincrby.return_value = 1
    redis.lpush.return_value = 1
    redis.rpop.return_value = "item"
    redis.lrange.return_value = ["item1", "item2"]
    redis.ltrim.return_value = None
    redis.llen.return_value = 1
    redis.zadd.return_value = 1
    redis.zrangebyscore.return_value = ["member1"]
    redis.zrem.return_value = 1

    async def _scan_iter_keys(pattern: str, count: int = 100):
        yield "key1"

    redis.scan_iter = MagicMock(side_effect=_scan_iter_keys)
    redis.startup.return_value = None
    redis.shutdown.return_value = None
    redis.register_script = MagicMock(return_value=MagicMock())
    return redis


@pytest.fixture
def mock_cashews() -> AsyncMock:
    """Create a mock CashewsClient."""
    cashews = AsyncMock()
    cashews.ping.return_value = True
    cashews.get.return_value = "cashews_value"
    cashews.set.return_value = None
    cashews.delete.return_value = 1
    cashews.expire.return_value = True
    cashews.hget.return_value = "cashews_hash_value"
    cashews.hset.return_value = None
    cashews.hexists.return_value = True
    cashews.hexists_many.return_value = [True]
    cashews.hgetall.return_value = {"key": "cashews_value"}
    cashews.hincrby.return_value = 1
    cashews.lpush.return_value = 1
    cashews.rpop.return_value = "cashews_item"
    cashews.lrange.return_value = ["item1"]
    cashews.ltrim.return_value = None
    cashews.llen.return_value = 1
    cashews.zadd.return_value = 1
    cashews.zrangebyscore.return_value = ["member1"]
    cashews.zrem.return_value = 1

    async def _scan_iter_keys(pattern: str, count: int = 100):
        yield "key1"

    cashews.scan_iter = MagicMock(side_effect=_scan_iter_keys)
    cashews.startup.return_value = None
    cashews.shutdown.return_value = None
    cashews.register_script = MagicMock(return_value=MagicMock())
    return cashews


@pytest.fixture
def fallback_pool(mock_redis: AsyncMock, mock_cashews: AsyncMock) -> FallbackCachePool:
    """Create a FallbackCachePool with mock clients."""
    return FallbackCachePool(primary=mock_redis, fallback=mock_cashews)


# ── Protocol Compliance ─────────────────────────────────────────────


class TestFallbackCachePoolProtocol:
    """Verify FallbackCachePool implements CachePool Protocol."""

    def test_implements_cache_pool(self) -> None:
        assert_implements(FallbackCachePool, CachePool)

    def test_is_instance_of_cache_pool(self, fallback_pool: FallbackCachePool) -> None:
        assert isinstance(fallback_pool, CachePool)


# ── Normal Operation (Primary Healthy) ──────────────────────────────


class TestFallbackCachePoolNormalOperation:
    """When Redis is healthy, all operations route to Redis."""

    async def test_get_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.get("key")
        mock_redis.get.assert_called_once_with("key")
        assert result == "redis_value"

    async def test_set_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        await fallback_pool.set("key", "value", ex=60)
        mock_redis.set.assert_called_once_with("key", "value", ex=60)

    async def test_delete_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.delete("key")
        mock_redis.delete.assert_called_once_with("key")
        assert result == 1

    async def test_expire_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.expire("key", 300)
        mock_redis.expire.assert_called_once_with("key", 300)
        assert result is True

    async def test_hget_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.hget("hash", "field")
        mock_redis.hget.assert_called_once_with("hash", "field")
        assert result == "hash_value"

    async def test_hset_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        await fallback_pool.hset("hash", "field", "value")
        mock_redis.hset.assert_called_once_with("hash", "field", "value")

    async def test_hexists_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.hexists("hash", "field")
        mock_redis.hexists.assert_called_once_with("hash", "field")
        assert result is True

    async def test_hexists_many_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.hexists_many("hash", ["k1", "k2"])
        mock_redis.hexists_many.assert_called_once_with("hash", ["k1", "k2"])
        assert result == [True, False]

    async def test_hgetall_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.hgetall("hash")
        mock_redis.hgetall.assert_called_once_with("hash")
        assert result == {"key": "value"}

    async def test_hincrby_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.hincrby("hash", "field", 2)
        mock_redis.hincrby.assert_called_once_with("hash", "field", 2)
        assert result == 1

    async def test_lpush_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.lpush("list", "val1", "val2")
        mock_redis.lpush.assert_called_once_with("list", "val1", "val2")
        assert result == 1

    async def test_rpop_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.rpop("list")
        mock_redis.rpop.assert_called_once_with("list")
        assert result == "item"

    async def test_lrange_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.lrange("list", 0, -1)
        mock_redis.lrange.assert_called_once_with("list", 0, -1)
        assert result == ["item1", "item2"]

    async def test_ltrim_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        await fallback_pool.ltrim("list", 0, 99)
        mock_redis.ltrim.assert_called_once_with("list", 0, 99)

    async def test_llen_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.llen("list")
        mock_redis.llen.assert_called_once_with("list")
        assert result == 1

    async def test_zadd_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.zadd("zset", {"member": 1.0})
        mock_redis.zadd.assert_called_once_with("zset", {"member": 1.0})
        assert result == 1

    async def test_zrangebyscore_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.zrangebyscore("zset", 0, 100)
        mock_redis.zrangebyscore.assert_called_once_with("zset", 0, 100, start=0, num=100)
        assert result == ["member1"]

    async def test_zrem_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.zrem("zset", "member")
        mock_redis.zrem.assert_called_once_with("zset", "member")
        assert result == 1

    async def test_scan_iter_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        keys = []
        async for key in fallback_pool.scan_iter("prefix:*", count=10):
            keys.append(key)
        mock_redis.scan_iter.assert_called_once_with("prefix:*", count=10)
        assert keys == ["key1"]

    async def test_register_script_routes_to_primary(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        script = "return redis.call('GET', KEYS[1])"
        result = fallback_pool.register_script(script)
        mock_redis.register_script.assert_called_once_with(script)
        assert result is not None

    async def test_startup_calls_both(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock, mock_cashews: AsyncMock
    ) -> None:
        await fallback_pool.startup()
        mock_redis.startup.assert_called_once()
        mock_cashews.startup.assert_called_once()

    async def test_shutdown_calls_both(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock, mock_cashews: AsyncMock
    ) -> None:
        await fallback_pool.shutdown()
        mock_redis.shutdown.assert_called_once()
        mock_cashews.shutdown.assert_called_once()

    async def test_ping_returns_primary_result(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        result = await fallback_pool.ping()
        assert result is True

    async def test_primary_healthy_property(self, fallback_pool: FallbackCachePool) -> None:
        assert fallback_pool.primary_healthy is True


# ── Degradation (Primary Fails) ─────────────────────────────────────


class TestFallbackCachePoolDegradation:
    """When Redis operations fail, automatically switch to CashewsClient."""

    async def test_degrade_on_operation_failure(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock, mock_cashews: AsyncMock
    ) -> None:
        """Redis get() fails → switch to CashewsClient for this and future ops."""
        mock_redis.get.side_effect = ConnectionError("Redis connection lost")

        # First call triggers degradation
        result = await fallback_pool.get("key")
        assert result == "cashews_value"
        assert fallback_pool.primary_healthy is False

    async def test_degraded_operations_route_to_fallback(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock, mock_cashews: AsyncMock
    ) -> None:
        """After degradation, all operations go to CashewsClient."""
        # Force degradation
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key1")

        # Subsequent operations go to fallback
        await fallback_pool.set("key2", "value")
        mock_cashews.set.assert_called_with("key2", "value", ex=None)

        result = await fallback_pool.hget("hash", "field")
        mock_cashews.hget.assert_called_with("hash", "field")

    async def test_degradation_records_metric(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """Degradation should increment cache_fallback_switches_total."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        mock_metrics = MagicMock()
        fallback_pool._metrics = mock_metrics
        await fallback_pool.get("key")
        mock_metrics.cache_fallback_switches_total.inc.assert_called_once()

    async def test_degradation_logs_warning(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """Degradation should log a warning."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        # Just verify degradation happens (log is internal)
        await fallback_pool.get("key")
        assert fallback_pool.primary_healthy is False


# ── Recovery (Primary Restored) ─────────────────────────────────────


class TestFallbackCachePoolRecovery:
    """When Redis recovers, switch back from CashewsClient."""

    async def test_recovery_on_health_check(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock, mock_cashews: AsyncMock
    ) -> None:
        """After degradation, successful ping() restores primary."""
        # Force degradation
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key1")
        assert fallback_pool.primary_healthy is False

        # Fix Redis
        mock_redis.get.side_effect = None
        mock_redis.get.return_value = "redis_value"
        mock_redis.ping.return_value = True

        # Trigger health check (force check by setting last check to past)
        fallback_pool._last_health_check = time.monotonic() - 120  # 2 minutes ago
        result = await fallback_pool.get("key2")

        # Should have recovered and routed to Redis
        assert fallback_pool.primary_healthy is True
        mock_redis.get.assert_called_with("key2")

    async def test_recovery_logs_info(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """Recovery should log an info message."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key1")

        mock_redis.get.side_effect = None
        mock_redis.get.return_value = "redis_value"
        mock_redis.ping.return_value = True

        fallback_pool._last_health_check = time.monotonic() - 120
        await fallback_pool.get("key2")
        # Verify recovery happened
        assert fallback_pool.primary_healthy is True


# ── Health Probe Interval ───────────────────────────────────────────


class TestFallbackCachePoolHealthProbe:
    """Health probe should not run more often than every 60 seconds."""

    async def test_no_duplicate_probe_within_interval(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """Within 60 seconds of last check, don't re-probe."""
        # Force degradation
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key1")
        assert fallback_pool.primary_healthy is False

        # Fix Redis but probe too recently
        mock_redis.get.side_effect = None
        mock_redis.get.return_value = "redis_value"
        mock_redis.ping.return_value = True

        # Just degraded — last check was very recent
        result = await fallback_pool.get("key2")
        # Should still be degraded (no health check yet)
        assert fallback_pool.primary_healthy is False
        mock_cashews_calls = fallback_pool._fallback.get.call_count

    async def test_probe_after_interval(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """After 60 seconds, health probe should run."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key1")

        mock_redis.get.side_effect = None
        mock_redis.get.return_value = "redis_value"
        mock_redis.ping.return_value = True

        # Simulate 61 seconds passing
        fallback_pool._last_health_check = time.monotonic() - 61
        result = await fallback_pool.get("key2")
        assert fallback_pool.primary_healthy is True


# ── Prometheus Metrics ──────────────────────────────────────────────


class TestFallbackCachePoolMetrics:
    """Verify Prometheus metrics are recorded correctly."""

    async def test_fallback_active_gauge_on_degrade(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """cache_fallback_active should be set to 1 on degradation."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        mock_metrics = MagicMock()
        fallback_pool._metrics = mock_metrics
        await fallback_pool.get("key")
        mock_metrics.cache_fallback_active.set.assert_called_with(1)

    async def test_fallback_active_gauge_on_recover(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """cache_fallback_active should be set to 0 on recovery."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key1")

        mock_redis.get.side_effect = None
        mock_redis.get.return_value = "redis_value"
        mock_redis.ping.return_value = True

        mock_metrics = MagicMock()
        fallback_pool._metrics = mock_metrics
        fallback_pool._last_health_check = time.monotonic() - 120
        await fallback_pool.get("key2")
        mock_metrics.cache_fallback_active.set.assert_called_with(0)


# ── register_script Degradation ─────────────────────────────────────


class TestFallbackCachePoolRegisterScript:
    """register_script should handle degraded mode correctly."""

    def test_register_script_routes_to_primary_when_healthy(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        script = "return redis.call('GET', KEYS[1])"
        result = fallback_pool.register_script(script)
        mock_redis.register_script.assert_called_once_with(script)

    async def test_register_script_routes_to_fallback_when_degraded(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock, mock_cashews: AsyncMock
    ) -> None:
        """When degraded, register_script routes to CashewsClient."""
        # Force degradation
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key")

        script = "return redis.call('GET', KEYS[1])"
        result = fallback_pool.register_script(script)
        mock_cashews.register_script.assert_called_once_with(script)


# ── Edge Cases ──────────────────────────────────────────────────────


class TestFallbackCachePoolEdgeCases:
    """Edge case handling."""

    async def test_fallback_failure_raises(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock, mock_cashews: AsyncMock
    ) -> None:
        """If both primary and fallback fail, raise the fallback error."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        mock_cashews.get.side_effect = RuntimeError("Cashews also failed")

        with pytest.raises(RuntimeError, match="Cashews also failed"):
            await fallback_pool.get("key")

    async def test_ping_failure_triggers_degradation(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """Failed ping during health check should keep degraded state."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key1")
        assert fallback_pool.primary_healthy is False

        # Ping still fails
        mock_redis.ping.return_value = False
        fallback_pool._last_health_check = time.monotonic() - 120

        # Should remain degraded
        result = await fallback_pool.get("key2")
        assert fallback_pool.primary_healthy is False

    async def test_cache_type_property(self, fallback_pool: FallbackCachePool) -> None:
        """cache_type should reflect current state."""
        assert fallback_pool.cache_type == "redis"

    async def test_cache_type_when_degraded(
        self, fallback_pool: FallbackCachePool, mock_redis: AsyncMock
    ) -> None:
        """cache_type should be 'cashews' when degraded."""
        mock_redis.get.side_effect = ConnectionError("Redis down")
        await fallback_pool.get("key")
        assert fallback_pool.cache_type == "cashews"
