# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Per-host rate limiter for fetcher module."""

from __future__ import annotations

import asyncio
import random
import time
from collections import OrderedDict
from urllib.parse import urlparse

from cachetools import LRUCache

from core.observability import get_logger

log = get_logger(__name__)

# Maximum number of host locks to retain (prevents memory leak)
MAX_HOST_LOCKS = 1000
MAX_HOST_TIMESTAMPS = 1000


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
            key: Host identifier.

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


class HostRateLimiter:
    """Per-host rate limiter with random delay.

    Ensures a minimum delay between requests to the same host.
    Uses random delay to appear more human-like and avoid rate limiting.

    Args:
        delay_min: Minimum delay between requests (seconds).
        delay_max: Maximum delay between requests (seconds).
    """

    def __init__(
        self,
        delay_min: float = 1.0,
        delay_max: float = 3.0,
    ) -> None:
        self._delay_min = delay_min
        self._delay_max = delay_max
        self._last_request: LRUCache[str, float] = LRUCache(maxsize=MAX_HOST_TIMESTAMPS)
        self._locks: BoundedLockDict = BoundedLockDict(maxsize=MAX_HOST_LOCKS)

    async def acquire(self, url: str) -> float:
        """Wait if necessary before allowing a request to the host.

        Args:
            url: The URL to be fetched.

        Returns:
            Time waited in seconds (0 if no wait needed).
        """
        host = urlparse(url).netloc

        async with self._locks[host]:
            now = time.monotonic()
            last = self._last_request.get(host, 0.0)
            elapsed = now - last

            delay = random.uniform(self._delay_min, self._delay_max)

            if last > 0 and elapsed < delay:
                wait_time = delay - elapsed
                log.debug(
                    "rate_limit_wait",
                    host=host,
                    wait_seconds=round(wait_time, 2),
                )
                await asyncio.sleep(wait_time)
                self._last_request[host] = time.monotonic()
                return wait_time

            self._last_request[host] = now
            return 0.0
