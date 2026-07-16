# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Article processing queue with Redis persistence and soft backpressure."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from core.observability import get_logger

if TYPE_CHECKING:
    from core.protocols import CachePool

log = get_logger(__name__)

QUEUE_KEY = "weaver:processing:pending"
MAX_QUEUE_SIZE = 200


class ProcessingQueue:
    """Redis-backed FIFO queue with soft size limit.

    Uses CachePool protocol for persistence. Producer checks length before
    enqueue to implement soft backpressure (skips if full, not blocking).

    FIFO semantics: lpush (prepend) + rpop (remove from right).
    """

    def __init__(self, cache: CachePool) -> None:
        self._cache = cache

    async def enqueue(self, article_id: str, task_id: str | None = None) -> bool:
        """Enqueue article for processing.

        Args:
            article_id: Article UUID string.
            task_id: Optional task UUID for tracking.

        Returns:
            True if enqueued, False if queue full (soft backpressure).
        """
        # Validate UUID format
        try:
            uuid.UUID(article_id)
        except ValueError:
            raise ValueError(f"Invalid UUID format: {article_id!r}")

        current_len = await self._cache.llen(QUEUE_KEY)
        if current_len >= MAX_QUEUE_SIZE:
            log.warning("processing_queue_full", size=current_len, max=MAX_QUEUE_SIZE)
            return False

        # Store as "article_id:task_id" or "article_id:"
        payload = f"{article_id}:{task_id or ''}"
        await self._cache.lpush(QUEUE_KEY, payload)
        log.debug("article_enqueued", article_id=article_id, queue_len=current_len + 1)
        return True

    async def dequeue(self) -> tuple[str, str | None] | None:
        """Dequeue article (FIFO: lpush + rpop).

        Returns:
            (article_id, task_id) or None if queue empty.
        """
        payload = await self._cache.rpop(QUEUE_KEY)
        if not payload:
            return None

        parts = payload.split(":")
        article_id = parts[0]
        task_id = parts[1] if len(parts) > 1 and parts[1] else None
        return (article_id, task_id)

    async def dequeue_batch(self, max_size: int = 20) -> list[tuple[str, str | None]]:
        """Dequeue multiple articles using LRANGE + LTRIM batch operation.

        Replaces N individual rpop calls with two Redis commands:
        LRANGE to fetch items, then LTRIM to atomically trim the list.

        Args:
            max_size: Maximum items to dequeue.

        Returns:
            List of (article_id, task_id) tuples.
        """
        if max_size <= 0:
            return []

        current_len = await self._cache.llen(QUEUE_KEY)
        if current_len == 0:
            return []

        count = min(max_size, current_len)

        # FIFO: items are at the right end (lpush prepends, rpop removes from right)
        raw_items = await self._cache.lrange(QUEUE_KEY, -count, -1)

        if count >= current_len:
            # All items dequeued — remove the key entirely
            await self._cache.delete(QUEUE_KEY)
        else:
            # Keep only items NOT dequeued (indices 0 to -(count+1))
            await self._cache.ltrim(QUEUE_KEY, 0, -(count + 1))

        items = []
        for payload in raw_items:
            parts = payload.split(":")
            article_id = parts[0]
            task_id = parts[1] if len(parts) > 1 and parts[1] else None
            items.append((article_id, task_id))
        return items

    async def length(self) -> int:
        """Get current queue length."""
        return await self._cache.llen(QUEUE_KEY)

    async def clear(self) -> None:
        """Clear all items from queue (for testing/reset)."""
        while await self._cache.rpop(QUEUE_KEY):
            pass
        log.info("processing_queue_cleared")
