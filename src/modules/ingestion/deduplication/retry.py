# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Dead-letter retry queue for failed crawl items."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import json_repair

from core.constants import RedisKeys
from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger(__name__)


class RetryQueue:
    """Cache-backed retry queue with host-level bucketing.

    Failed items are stored in a sorted set keyed by host,
    with the score being the next retry timestamp.

    Supports a dead-letter list for permanently failed items
    (after max retries).

    Implements: RetryStrategy

    Args:
        cache: Cache pool instance.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds for exponential backoff.
    """

    DEAD_LETTER_KEY = RedisKeys.CRAWL_DEAD_LETTER

    def __init__(
        self,
        cache: CachePool,
        max_retries: int = 3,
        base_delay: float = 60.0,
    ) -> None:
        self._cache = cache
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
        key = RedisKeys.crawl_retry(host)

        payload = json.dumps(
            {
                "url": url,
                "host": host,
                "attempt": attempt + 1,
                "enqueued_at": time.time(),
            }
        )

        await self._cache.zadd(key, {payload: next_retry})
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
        key = RedisKeys.crawl_retry(host)
        now = time.time()

        items = await self._cache.zrangebyscore(key, 0, now, num=50)
        result = []
        for item_str in items:
            item = json_repair.loads(item_str)
            # json_repair.loads returns '' for invalid JSON (instead of raising)
            if not isinstance(item, dict):
                log.warning(
                    "invalid_retry_item",
                    raw=item_str[:100],
                )
                continue
            required_fields = ("url", "host")
            if not all(f in item for f in required_fields):
                log.warning(
                    "missing_fields_in_retry_item",
                    fields=list(item.keys()),
                )
                continue

            # Validate field types
            url = item.get("url")
            host = item.get("host")
            if not isinstance(url, str) or not url:
                log.warning(
                    "invalid_retry_item_url",
                    url_type=type(url).__name__,
                    raw=item_str[:100],
                )
                continue
            if not isinstance(host, str) or not host:
                log.warning(
                    "invalid_retry_item_host",
                    host_type=type(host).__name__,
                    raw=item_str[:100],
                )
                continue
            attempt = item.get("attempt")
            if attempt is not None and not (isinstance(attempt, int) and attempt >= 0):
                log.warning(
                    "invalid_retry_item_attempt",
                    attempt=attempt,
                    raw=item_str[:100],
                )
                continue
            next_retry_at = item.get("next_retry_at")
            if next_retry_at is not None and not isinstance(next_retry_at, (int, float)):
                log.warning(
                    "invalid_retry_item_next_retry_at",
                    next_retry_at=next_retry_at,
                    raw=item_str[:100],
                )
                continue

            result.append(item)

        # Remove fetched items from the sorted set
        if items:
            await self._cache.zrem(key, *items)

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
        await self._cache.lpush(self.DEAD_LETTER_KEY, payload)
        log.warning(
            "move_to_dead_letter",
            url=url,
            host=host,
            attempts=attempt,
        )
