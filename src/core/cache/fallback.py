# Copyright (c) 2026 KirkyX. All Rights Reserved
"""FallbackCachePool — runtime Redis→Cashews degradation proxy.

Implements:
    - CachePool: Unified cache operations with automatic failover

Holds both a primary (Redis) and fallback (CashewsClient) client.
When the primary fails, automatically degrades to the fallback.
Periodically probes the primary and recovers when it becomes available.

Design:
    - Health probe interval: 60 seconds
    - Degradation: any operation exception on primary triggers fallback
    - Recovery: successful ping() during health check restores primary
    - Metrics: cache_fallback_active (Gauge), cache_fallback_switches_total (Counter)
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from core.observability import get_logger

log = get_logger(__name__)

# Minimum seconds between health probes to the primary
_HEALTH_PROBE_INTERVAL_SECONDS = 60


class FallbackCachePool:
    """Proxy cache pool with automatic Redis→Cashews runtime degradation.

    Implements:
        - CachePool: Async cache operations with automatic failover
    """

    def __init__(self, primary: Any, fallback: Any) -> None:
        """Initialize with primary (Redis) and fallback (CashewsClient) clients.

        Args:
            primary: Primary cache client (RedisClient).
            fallback: Fallback cache client (CashewsClient).
        """
        self._primary = primary
        self._fallback = fallback
        self._primary_healthy: bool = True
        self._last_health_check: float = 0.0

        # Import metrics lazily to avoid circular imports at module level
        try:
            from core.observability.metrics import metrics

            self._metrics = metrics
        except ImportError:
            self._metrics = None  # type: ignore[assignment]

    # ── Properties ─────────────────────────────────────────────────

    @property
    def primary_healthy(self) -> bool:
        """Whether the primary (Redis) client is currently healthy."""
        return self._primary_healthy

    @property
    def cache_type(self) -> str:
        """Current active cache backend type: 'redis' or 'cashews'."""
        return "redis" if self._primary_healthy else "cashews"

    # ── Lifecycle ──────────────────────────────────────────────────

    async def startup(self) -> None:
        """Initialize both primary and fallback clients."""
        try:
            await self._primary.startup()
        except Exception as exc:
            log.warning(
                "fallback_cache_primary_startup_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            self._primary_healthy = False
            self._set_fallback_active(1)

        await self._fallback.startup()

    async def shutdown(self) -> None:
        """Close both primary and fallback clients."""
        try:
            await self._primary.shutdown()
        except Exception as exc:
            log.debug(
                "fallback_cache_primary_shutdown_failed",
                error=str(exc),
            )
        await self._fallback.shutdown()

    async def ping(self) -> bool:
        """Check primary connectivity; fall back if unhealthy."""
        if self._primary_healthy:
            try:
                return await self._primary.ping()
            except Exception:
                return False
        return await self._fallback.ping()

    # ── Health Probe ───────────────────────────────────────────────

    async def _maybe_probe_primary(self) -> None:
        """Probe primary health if enough time has elapsed since last check."""
        now = time.monotonic()
        if now - self._last_health_check < _HEALTH_PROBE_INTERVAL_SECONDS:
            return

        self._last_health_check = now
        try:
            healthy = await self._primary.ping()
            if healthy and not self._primary_healthy:
                self._primary_healthy = True
                self._set_fallback_active(0)
                log.info(
                    "fallback_cache_primary_recovered",
                    message="Redis recovered — switching back to primary",
                )
        except Exception:
            # Primary still unhealthy, stay degraded
            pass

    def _degrade_to_fallback(self, operation: str, error: Exception) -> None:
        """Switch to fallback client and record metrics."""
        if self._primary_healthy:
            self._primary_healthy = False
            self._last_health_check = time.monotonic()
            self._set_fallback_active(1)
            self._increment_switches()
            log.warning(
                "fallback_cache_degraded",
                operation=operation,
                error=str(error),
                exc_type=type(error).__name__,
                message="Redis operation failed — degrading to CashewsClient",
            )

    def _set_fallback_active(self, value: int) -> None:
        """Set cache_fallback_active gauge."""
        if self._metrics is not None:
            with contextlib.suppress(Exception):
                self._metrics.cache_fallback_active.set(value)

    def _increment_switches(self) -> None:
        """Increment cache_fallback_switches_total counter."""
        if self._metrics is not None:
            with contextlib.suppress(Exception):
                self._metrics.cache_fallback_switches_total.inc()

    # ── Internal Routing ───────────────────────────────────────────

    async def _execute(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        """Execute an operation on primary, falling back on failure.

        Args:
            operation: Method name to call on the cache client.
            *args: Positional arguments for the method.
            **kwargs: Keyword arguments for the method.

        Returns:
            Result from primary (if healthy) or fallback.
        """
        if self._primary_healthy:
            try:
                method = getattr(self._primary, operation)
                return await method(*args, **kwargs)
            except Exception as exc:
                self._degrade_to_fallback(operation, exc)
                # Fall through to fallback

        # Degraded path: try health probe first, then use fallback
        await self._maybe_probe_primary()

        if self._primary_healthy:
            # Recovered during probe
            try:
                method = getattr(self._primary, operation)
                return await method(*args, **kwargs)
            except Exception as exc:
                self._degrade_to_fallback(operation, exc)

        method = getattr(self._fallback, operation)
        return await method(*args, **kwargs)

    # ── Key/Value Operations ───────────────────────────────────────

    async def get(self, key: str) -> str | None:
        return await self._execute("get", key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        return await self._execute("set", key, value, ex=ex)

    async def delete(self, *keys: str) -> int:
        return await self._execute("delete", *keys)

    async def expire(self, name: str, seconds: int) -> bool:
        return await self._execute("expire", name, seconds)

    # ── Hash Operations ────────────────────────────────────────────

    async def hget(self, name: str, key: str) -> str | None:
        return await self._execute("hget", name, key)

    async def hset(self, name: str, key: str, value: str) -> None:
        return await self._execute("hset", name, key, value)

    async def hexists(self, name: str, key: str) -> bool:
        return await self._execute("hexists", name, key)

    async def hexists_many(self, name: str, keys: list[str]) -> list[bool]:
        return await self._execute("hexists_many", name, keys)

    async def hgetall(self, name: str) -> dict[str, str]:
        return await self._execute("hgetall", name)

    async def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        return await self._execute("hincrby", name, key, amount)

    # ── List Operations ────────────────────────────────────────────

    async def lpush(self, name: str, *values: str) -> int:
        return await self._execute("lpush", name, *values)

    async def rpop(self, name: str) -> str | None:
        return await self._execute("rpop", name)

    async def lrange(self, name: str, start: int, stop: int) -> list[str]:
        return await self._execute("lrange", name, start, stop)

    async def ltrim(self, name: str, start: int, stop: int) -> None:
        return await self._execute("ltrim", name, start, stop)

    async def llen(self, name: str) -> int:
        return await self._execute("llen", name)

    # ── Sorted Set Operations ──────────────────────────────────────

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        return await self._execute("zadd", name, mapping)

    async def zrangebyscore(
        self,
        name: str,
        min_score: float,
        max_score: float,
        start: int = 0,
        num: int = 100,
    ) -> list[str]:
        return await self._execute(
            "zrangebyscore", name, min_score, max_score, start=start, num=num
        )

    async def zrem(self, name: str, *members: str) -> int:
        return await self._execute("zrem", name, *members)

    # ── Scan Operations ────────────────────────────────────────────

    async def scan(
        self, cursor: int = 0, match: str | None = None, count: int = 10
    ) -> tuple[int, list[str]]:
        return await self._execute("scan", cursor, match=match, count=count)

    # ── Script Operations ──────────────────────────────────────────

    def register_script(self, script: str) -> Any:
        """Register a Lua script with the active client.

        When degraded, routes to CashewsClient (which returns a
        _CashewsScript that raises NotImplementedError on call).

        Args:
            script: Lua script text.

        Returns:
            Script object from the active client.
        """
        client = self._primary if self._primary_healthy else self._fallback
        return client.register_script(script)
