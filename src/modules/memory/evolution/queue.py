# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Redis-backed queue for slow path consolidation events.

Provides async queue operations for decoupling Fast Path ingestion
from Slow Path consolidation.
"""

from __future__ import annotations

from typing import Protocol

from core.observability.logging import get_logger

log = get_logger("consolidation_queue")


class RedisClientProtocol(Protocol):
    """Protocol for Redis client interface."""

    async def lpush(self, key: str, value: str) -> int: ...

    async def rpop(self, key: str) -> str | None: ...

    async def llen(self, key: str) -> int: ...


class ConsolidationQueue:
    """Redis-backed queue for pending consolidation events.

    Events are enqueued by Fast Path and dequeued by Slow Path worker.
    Uses LIST data structure for FIFO ordering.
    """

    def __init__(
        self,
        redis: RedisClientProtocol,
        key_prefix: str = "weaver:memory:consolidation",
    ) -> None:
        """Initialize consolidation queue.

        Args:
            redis: Redis client instance.
            key_prefix: Redis key prefix for queue storage.
        """
        self._redis = redis
        self._key_prefix = key_prefix
        self._pending_key = f"{key_prefix}:pending"

    async def enqueue(self, event_id: str) -> bool:
        """Add an event to the consolidation queue.

        Args:
            event_id: ID of the event to consolidate.

        Returns:
            True if enqueued successfully.
        """
        try:
            await self._redis.lpush(self._pending_key, event_id)
            log.debug("consolidation_event_enqueued", event_id=event_id)
            return True
        except Exception as exc:
            log.error(
                "consolidation_enqueue_failed",
                event_id=event_id,
                error=str(exc),
            )
            return False

    async def dequeue(self) -> str | None:
        """Remove and return the next event from the queue.

        Returns:
            Event ID if available, None if queue is empty.
        """
        try:
            event_id = await self._redis.rpop(self._pending_key)
            if event_id:
                log.debug("consolidation_event_dequeued", event_id=event_id)
            return event_id
        except Exception as exc:
            log.error("consolidation_dequeue_failed", error=str(exc))
            return None

    async def length(self) -> int:
        """Get the number of pending events in the queue.

        Returns:
            Queue length.
        """
        try:
            return await self._redis.llen(self._pending_key)
        except Exception:
            return 0
