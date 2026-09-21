# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Request delay controller for LLM clients."""

from __future__ import annotations

import asyncio
import random
import time
from collections import OrderedDict

from cachetools import LRUCache

from core.observability import get_logger

log = get_logger(__name__)

# Maximum number of provider locks to retain (prevents memory leak)
MAX_PROVIDER_LOCKS = 1000
MAX_PROVIDER_TIMESTAMPS = 1000


class BoundedLockDict:
    """Bounded dictionary for asyncio.Lock with LRU eviction.

    Creates locks on demand and evicts least recently used entries
    when capacity is reached. Safe for async context because eviction
    only occurs when adding new keys, not when accessing existing ones.

    Eviction safety (mirrors fetching/rate_limiter.py): a lock that is
    held or awaited is never evicted — evicting a busy lock would let a
    new lock be created for the same provider, so two coroutines could
    pass the critical section simultaneously and the per-provider
    minimum delay would collapse to ~0.

    Args:
        maxsize: Maximum number of locks to retain.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._maxsize = maxsize
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        # Per-key in-flight counter (holders + waiters). ``locked()`` alone
        # misses the window between release() and the queued waiter's
        # resumption, where the lock reports unlocked — evicting there
        # would split the provider's critical section across two locks.
        self._in_flight: dict[str, int] = {}

    def mark_in_flight(self, key: str) -> None:
        """Record a caller about to acquire the lock for ``key``."""
        self._in_flight[key] = self._in_flight.get(key, 0) + 1

    def mark_done(self, key: str) -> None:
        """Record a caller finished with the lock for ``key``."""
        remaining = self._in_flight.get(key, 0) - 1
        if remaining > 0:
            self._in_flight[key] = remaining
        else:
            self._in_flight.pop(key, None)

    def __getitem__(self, key: str) -> asyncio.Lock:
        """Get lock for key, creating if necessary.

        Args:
            key: Provider/host identifier.

        Returns:
            asyncio.Lock for the key.
        """
        if key in self._locks:
            # Move to end (most recently used)
            self._locks.move_to_end(key)
            return self._locks[key]

        # Create new lock
        if len(self._locks) >= self._maxsize:
            # Evict the oldest idle lock only
            oldest_key: str | None = None
            for candidate_key in self._locks:
                if candidate_key in self._in_flight:
                    continue
                if not self._locks[candidate_key].locked():
                    oldest_key = candidate_key
                    break
            if oldest_key is not None:
                log.debug("lock_evicted", key=oldest_key, reason="capacity_reached")
                del self._locks[oldest_key]
            else:
                # All locks are in use — temporarily exceed maxsize rather
                # than evicting a busy lock (bounded by concurrent providers).
                log.debug(
                    "lock_cache_over_capacity",
                    size=len(self._locks),
                    maxsize=self._maxsize,
                )

        lock = asyncio.Lock()
        self._locks[key] = lock
        return lock

    def __contains__(self, key: str) -> bool:
        return key in self._locks

    def __len__(self) -> int:
        return len(self._locks)


class RequestDelay:
    """LLM请求延迟控制器.

    在每次LLM请求前添加随机时间间隔,避免请求过于集中.
    参考fetcher模块的HostRateLimiter实现,适配LLM调用场景.

    Thread-safety:
        仅对单事件循环（单线程 asyncio）安全。``_last_request_time`` 使用
        ``cachetools.LRUCache``，其读写并非原子；若未来从多 OS 线程访问，
        需要用 ``threading.Lock`` 保护该缓存。

    Args:
        enabled: 是否启用延迟
        delay_min: 最小延迟时间（秒）
        delay_max: 最大延迟时间（秒）
    """

    def __init__(
        self,
        enabled: bool = False,
        delay_min: float = 1.0,
        delay_max: float = 2.0,
    ) -> None:
        """初始化延迟控制器.

        Args:
            enabled: 是否启用延迟
            delay_min: 最小延迟时间（秒）
            delay_max: 最大延迟时间（秒）
        """
        self._enabled = enabled
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._last_request_time: LRUCache[str, float] = LRUCache(maxsize=MAX_PROVIDER_TIMESTAMPS)
        self._locks: BoundedLockDict = BoundedLockDict(maxsize=MAX_PROVIDER_LOCKS)

    async def acquire(self, provider: str) -> float:
        """在请求前调用此方法,等待必要的延迟时间.

        Args:
            provider: Provider名称

        Returns:
            实际等待时间（秒）,如果未启用或无需等待则返回0.0
        """
        # 如果未启用,直接返回
        if not self._enabled:
            return 0.0

        # 获取provider特定的锁
        # mark_in_flight keeps the lock alive across the acquire-to-release
        # span: without it an LRU eviction between two requests of the same
        # provider could hand waiters a stale lock (see BoundedLockDict).
        self._locks.mark_in_flight(provider)
        try:
            async with self._locks[provider]:
                # 计算距离上次请求的时间
                now = time.monotonic()
                last_time = self._last_request_time.get(provider, 0.0)
                elapsed = now - last_time

                # 生成随机延迟
                # 延迟抖动非密码学用途
                delay = random.uniform(self._delay_min, self._delay_max)  # nosec B311

                # 如果距离上次请求时间小于延迟,则等待
                if elapsed < delay:
                    wait_time = delay - elapsed
                    log.debug(
                        "request_delay_wait",
                        provider=provider,
                        wait_seconds=round(wait_time, 2),
                        elapsed=round(elapsed, 2),
                        target_delay=round(delay, 2),
                    )
                    await asyncio.sleep(wait_time)
                    self._last_request_time[provider] = time.monotonic()
                    return wait_time

                # 无需等待,更新时间戳
                self._last_request_time[provider] = now
                return 0.0
        finally:
            self._locks.mark_done(provider)
