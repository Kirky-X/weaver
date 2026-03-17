"""Per-host rate limiter for fetcher module."""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from urllib.parse import urlparse

from core.observability.logging import get_logger

log = get_logger("fetcher_rate_limiter")


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
        self._last_request: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

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
            last = self._last_request[host]
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
