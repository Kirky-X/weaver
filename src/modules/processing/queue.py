# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Article processing queue with Redis persistence and soft backpressure."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols.pools import CachePool

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
        """Dequeue multiple articles.

        Args:
            max_size: Maximum items to dequeue.

        Returns:
            List of (article_id, task_id) tuples.
        """
        items = []
        for _ in range(max_size):
            item = await self.dequeue()
            if not item:
                break
            items.append(item)
        return items

    async def length(self) -> int:
        """Get current queue length."""
        return await self._cache.llen(QUEUE_KEY)

    async def clear(self) -> None:
        """Clear all items from queue (for testing/reset)."""
        while await self._cache.rpop(QUEUE_KEY):
            pass
        log.info("processing_queue_cleared")
