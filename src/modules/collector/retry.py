# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Dead-letter retry queue for failed crawl items."""

from __future__ import annotations

import json
import time

import json_repair

from core.cache.redis import RedisClient
from core.observability.logging import get_logger

log = get_logger("retry_queue")


class RetryQueue:
    """Redis-backed retry queue with host-level bucketing.

    Failed items are stored in a sorted set keyed by host,
    with the score being the next retry timestamp.

    Supports a dead-letter list for permanently failed items
    (after max retries).

    Args:
        redis: Redis client instance.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds for exponential backoff.
    """

    DEAD_LETTER_KEY = "crawl:dead"

    def __init__(
        self,
        redis: RedisClient,
        max_retries: int = 3,
        base_delay: float = 60.0,
    ) -> None:
        self._redis = redis
        self._max_retries = max_retries
        self._base_delay = base_delay

    async def enqueue(self, url: str, host: str, attempt: int = 0) -> None:
        """Add a URL to the retry queue.

        Uses exponential backoff to calculate the next retry time.
        If max retries exceeded, moves to dead-letter queue.

        Args:
            url: The URL that failed.
            host: The host for bucketing.
            attempt: Current attempt number.
        """
        if attempt >= self._max_retries:
            await self._move_to_dead_letter(url, host, attempt)
            return

        delay = self._base_delay * (2**attempt)
        next_retry = time.time() + delay
        key = f"crawl:retry:{host}"

        payload = json.dumps(
            {
                "url": url,
                "host": host,
                "attempt": attempt + 1,
                "enqueued_at": time.time(),
            }
        )

        await self._redis.zadd(key, {payload: next_retry})
        log.debug(
            "retry_enqueued",
            url=url,
            host=host,
            attempt=attempt + 1,
            next_retry_in=delay,
        )

    async def get_due_items(self, host: str) -> list[dict]:
        """Get items that are due for retry.

        Args:
            host: The host to check.

        Returns:
            List of retry item dicts.
        """
        key = f"crawl:retry:{host}"
        now = time.time()

        items = await self._redis.zrangebyscore(key, 0, now, num=50)
        result = []
        for item_str in items:
            item = json_repair.loads(item_str)
            # json_repair.loads returns '' for invalid JSON (instead of raising)
            if not isinstance(item, (dict, list)):
                continue
            result.append(item)

        # Remove fetched items from the sorted set
        if items:
            await self._redis.zrem(key, *items)

        return result

    async def _move_to_dead_letter(self, url: str, host: str, attempt: int) -> None:
        """Move a permanently failed URL to the dead-letter queue."""
        payload = json.dumps(
            {
                "url": url,
                "host": host,
                "final_attempt": attempt,
                "dead_at": time.time(),
            }
        )
        await self._redis.lpush(self.DEAD_LETTER_KEY, payload)
        log.warning(
            "move_to_dead_letter",
            url=url,
            host=host,
            attempts=attempt,
        )
