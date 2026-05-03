# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Request delay controller for LLM clients."""

from __future__ import annotations

import asyncio
import random
import time
from collections import OrderedDict

from cachetools import LRUCache

from core.observability.logging import get_logger

log = get_logger(__name__)

# Maximum number of provider locks to retain (prevents memory leak)
MAX_PROVIDER_LOCKS = 1000
MAX_PROVIDER_TIMESTAMPS = 1000


class BoundedLockDict:
    """Bounded dictionary for asyncio.Lock with LRU eviction.

    Creates locks on demand and evicts least recently used entries
    when capacity is reached. Safe for async context because eviction
    only occurs when adding new keys, not when accessing existing ones.

    Args:
        maxsize: Maximum number of locks to retain.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._maxsize = maxsize
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

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
            # Evict oldest (first item)
            oldest_key = next(iter(self._locks))
            log.debug("lock_evicted", key=oldest_key, reason="capacity_reached")
            del self._locks[oldest_key]

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
        async with self._locks[provider]:
            # 计算距离上次请求的时间
            now = time.monotonic()
            last_time = self._last_request_time.get(provider, 0.0)
            elapsed = now - last_time

            # 生成随机延迟
            delay = random.uniform(self._delay_min, self._delay_max)

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
