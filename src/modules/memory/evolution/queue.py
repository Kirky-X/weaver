# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Redis-backed queue for slow path consolidation events.

Provides async queue operations for decoupling Fast Path ingestion
from Slow Path consolidation.

Delivery semantics: dequeued events are parked in a ``processing`` list
until ``ack`` confirms success, so a crash between pop and ack no longer
loses the event (at-least-once). Call ``recover_stale`` on worker startup
to requeue events left in the processing list by a previous crash.
"""

from __future__ import annotations

from core.observability import get_logger
from core.protocols import CachePool

log = get_logger(__name__)


class QueueBackendError(RuntimeError):
    """Raised when the queue backend (Redis) fails during dequeue.

    Distinct from an empty queue so consumers can tell "nothing to do"
    apart from "backend unavailable".
    """


class ConsolidationQueue:
    """Redis-backed queue for pending consolidation events.

    Events are enqueued by Fast Path and dequeued by Slow Path worker.
    Uses LIST data structure for FIFO ordering.
    """

    def __init__(
        self,
        redis: CachePool,
        key_prefix: str = "weaver:memory:consolidation",
    ) -> None:
        """Initialize consolidation queue.

        Args:
            redis: Cache pool instance.
            key_prefix: Redis key prefix for queue storage.
        """
        self._redis = redis
        self._key_prefix = key_prefix
        self._pending_key = f"{key_prefix}:pending"
        self._processing_key = f"{key_prefix}:processing"

    async def enqueue(self, event_id: str) -> bool:
        """Add an event to the consolidation queue.

        Idempotency: duplicate enqueues of the same ``event_id`` within the
        dedup window (24h) are suppressed via an atomic ``SET NX`` marker, so
        fast-path retries do not pile duplicate entries onto the list.
        Delivery remains at-least-once (see :meth:`dequeue`).

        Args:
            event_id: ID of the event to consolidate.

        Returns:
            True if enqueued (or duplicate-suppressed) successfully.
        """
        try:
            set_nx = getattr(self._redis, "set_nx", None)
            if set_nx is not None:
                try:
                    acquired = await set_nx(f"{self._pending_key}:dedup:{event_id}", "1", ex=86400)
                except Exception as exc:
                    log.warning(
                        "consolidation_dedup_check_failed",
                        event_id=event_id,
                        error=str(exc),
                    )
                    acquired = True
                if not acquired:
                    log.debug("consolidation_event_duplicate_suppressed", event_id=event_id)
                    return True
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

        The event is parked in the ``processing`` list until ``ack`` is
        called, giving at-least-once delivery: if the worker crashes after
        dequeue, ``recover_stale`` can requeue the parked event.

        Returns:
            Event ID if available, None if queue is empty.

        Raises:
            QueueBackendError: If the Redis backend fails — callers must
                distinguish this from an empty queue.
        """
        try:
            event_id = await self._redis.rpop(self._pending_key)
            if event_id:
                await self._redis.lpush(self._processing_key, event_id)
                log.debug("consolidation_event_dequeued", event_id=event_id)
            return event_id
        except Exception as exc:
            log.error("consolidation_dequeue_failed", error=str(exc), exc_info=True)
            raise QueueBackendError(f"queue backend failed: {exc}") from exc

    async def ack(self, event_id: str) -> None:
        """Mark an event as successfully processed.

        Removes it from the ``processing`` list.

        Args:
            event_id: ID of the processed event.
        """
        try:
            items = await self._redis.lrange(self._processing_key, 0, -1)
            if event_id not in items:
                return
            remaining = [i for i in items if i != event_id]
            await self._redis.delete(self._processing_key)
            if remaining:
                # lpush expects head-first order; keep original ordering
                await self._redis.lpush(self._processing_key, *reversed(remaining))
            try:
                await self._redis.delete(f"{self._pending_key}:dedup:{event_id}")
            except Exception as exc:
                log.warning(
                    "consolidation_dedup_clear_failed",
                    event_id=event_id,
                    error=str(exc),
                )
        except Exception as exc:
            # Leaving the event in the processing list is safe: it will be
            # requeued by recover_stale, only risking duplicate processing.
            log.warning(
                "consolidation_ack_failed",
                event_id=event_id,
                error=str(exc),
                exc_info=True,
            )

    async def recover_stale(self) -> int:
        """Requeue all events parked in the processing list.

        Called on worker startup to resume events left behind by a crashed
        run (at-least-once recovery).

        Returns:
            Number of events requeued.
        """
        try:
            items = await self._redis.lrange(self._processing_key, 0, -1)
            if not items:
                return 0
            await self._redis.delete(self._processing_key)
            # rpop consumes from the tail; push in reverse to keep FIFO order
            for event_id in reversed(items):
                await self._redis.lpush(self._pending_key, event_id)
            log.info("consolidation_stale_recovered", count=len(items))
            return len(items)
        except Exception as exc:
            log.error("consolidation_recover_failed", error=str(exc), exc_info=True)
            return 0

    async def length(self) -> int:
        """Get the number of pending events in the queue.

        Returns:
            Queue length.
        """
        try:
            return await self._redis.llen(self._pending_key)
        except Exception:
            log.warning("queue_length_failed", exc_info=True)
            return 0
