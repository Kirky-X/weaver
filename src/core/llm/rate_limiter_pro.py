# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Rate limiter using the professional `limits` library."""

from __future__ import annotations

import asyncio
from typing import Any

import limits
import limits.strategies
from limits.storage import MemoryStorage, RedisStorage

from core.observability.logging import get_logger

log = get_logger("rate_limiter")


class RateLimiter:
    """Professional rate limiter using the `limits` library.

    Supports:
    - Multiple strategies: Fixed Window, Moving Window, Token Bucket
    - Multiple storage backends: Memory, Redis
    - Per-provider rate limits
    """

    def __init__(
        self,
        storage_type: str = "memory",
        redis_url: str | None = None,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            storage_type: Storage backend type ("memory" or "redis")
            redis_url: Redis connection URL (required if storage_type is "redis")
        """
        self._storage_type = storage_type
        self._redis_url = redis_url
        self._storage: limits.storage.Storage = None
        self._strategies: dict[str, limits.strategies.FixedWindowRateLimiter] = {}
        self._limits: dict[str, limits.RateLimitItem] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the storage."""
        async with self._lock:
            if self._storage is not None:
                return

            if self._storage_type == "redis" and self._redis_url:
                self._storage = RedisStorage(uri=self._redis_url)
            else:
                self._storage = MemoryStorage()

            log.info("rate_limiter_initialized", storage=self._storage_type)

    def set_rate_limit(self, provider: str, rate: str) -> None:
        """Set rate limit for a provider.

        Args:
            provider: Provider name
            rate: Rate string (e.g., "60/minute", "10/second")
        """
        try:
            limit = limits.parse(rate)
            self._limits[provider] = limit
            self._strategies[provider] = limits.strategies.FixedWindowRateLimiter(self._storage)
            log.info("rate_limit_set", provider=provider, rate=rate)
        except Exception as e:
            log.error("invalid_rate_limit", provider=provider, rate=rate, error=str(e))

    async def acquire(
        self,
        provider: str,
        tokens: int = 1,
        rpm_limit: int = 0,
    ) -> float:
        """Acquire tokens, waiting if necessary.

        Args:
            provider: Provider name
            tokens: Number of tokens to acquire
            rpm_limit: RPM limit (if > 0, overrides provider setting)

        Returns:
            0.0 if acquired immediately, >0.0 seconds waited if had to wait
        """
        if self._storage is None:
            await self.initialize()

        if provider not in self._strategies:
            if rpm_limit > 0:
                limit = limits.parse(f"{rpm_limit}/minute")
                strategy = limits.strategies.FixedWindowRateLimiter(self._storage)
            else:
                return 0.0
        else:
            limit = self._limits.get(provider)
            strategy = self._strategies.get(provider)

            if rpm_limit > 0:
                limit = limits.parse(f"{rpm_limit}/minute")
                strategy = limits.strategies.FixedWindowRateLimiter(self._storage)

        if limit is None:
            return 0.0

        try:
            acquired = strategy.hit(limit, tokens)
            if acquired:
                return 0.0
            else:
                wait_time = self._get_wait_time(strategy, limit)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                return wait_time
        except Exception:
            wait_time = self._get_wait_time(strategy, limit)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            return wait_time

    def _get_wait_time(
        self, strategy: limits.strategies.FixedWindowRateLimiter, limit: limits.RateLimitItem
    ) -> float:
        """Get estimated wait time for the limit."""
        try:
            stats = strategy.get_window_stats(limit)
            if stats:
                return max(0.0, stats.reset_time - stats.time_remaining)
        except Exception:
            pass
        return 1.0

    async def try_acquire(self, provider: str, tokens: int = 1) -> bool:
        """Try to acquire tokens without waiting.

        Args:
            provider: Provider name
            tokens: Number of tokens to acquire

        Returns:
            True if acquired, False otherwise
        """
        if self._storage is None:
            await self.initialize()

        if provider not in self._strategies:
            return True

        limit = self._limits.get(provider)
        strategy = self._strategies.get(provider)

        if limit is None or strategy is None:
            return True

        try:
            return strategy.test(limit, tokens)
        except Exception:
            return False

    async def get_stats(self, provider: str) -> dict[str, Any]:
        """Get current rate limit statistics for a provider.

        Args:
            provider: Provider name

        Returns:
            Dictionary with limit info
        """
        if provider not in self._limits:
            return {"available": True, "limit": "unlimited"}

        limit = self._limits.get(provider)
        strategy = self._strategies.get(provider)

        if limit is None or strategy is None:
            return {"available": True, "limit": "unlimited"}

        try:
            stats = strategy.get_window_stats(limit)
            if stats:
                return {
                    "available": stats.available,
                    "limit": str(limit),
                    "remaining": stats.available,
                    "reset_in": stats.reset_time - stats.time_remaining,
                }
        except Exception as e:
            log.error("get_stats_error", provider=provider, error=str(e))

        return {"available": True, "limit": str(limit)}

    async def reset(self, provider: str | None = None) -> None:
        """Reset rate limit for a provider or all providers.

        Args:
            provider: Provider name, or None to reset all
        """
        if provider is None:
            self._limits.clear()
            self._strategies.clear()
            log.info("all_rate_limits_reset")
        else:
            self._limits.pop(provider, None)
            self._strategies.pop(provider, None)
            log.info("rate_limit_reset", provider=provider)

    async def close(self) -> None:
        """Close the rate limiter and cleanup resources."""
        if self._storage:
            self._storage = None
            self._limits.clear()
            self._strategies.clear()
            log.info("rate_limiter_closed")
