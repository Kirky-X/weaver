# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Memory event publisher collaborator.

Publishes ``MemoryIngestEvent`` for successfully processed articles so the
MAGMA memory subsystem can ingest them.

Extracted from ``Pipeline`` to keep the orchestrator focused on flow control.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.event import EventBus

log = get_logger(__name__)


class MemoryEventPublisher:
    """Publish memory ingest events for completed articles (outbox-backed).

    Single responsibility: build ``MemoryIngestEvent`` instances from
    non-terminal pipeline states, persist them to the transactional outbox
    (at-least-once), then dispatch them concurrently on the in-process bus.
    Rows dispatch successfully are marked immediately; leftovers are
    replayed by the ``dispatch_outbox_events`` scheduler job.

    Args:
        event_bus: Event bus used to publish memory ingest events.
        outbox_repo: Optional outbox repository; when None the publisher
            behaves fire-and-forget (legacy, crash-lossy).
    """

    def __init__(self, *, event_bus: EventBus, outbox_repo: Any | None = None) -> None:
        self._event_bus = event_bus
        self._outbox_repo = outbox_repo

    async def publish(self, states: list[PipelineState]) -> None:
        """Publish memory ingest events for successfully processed articles.

        Args:
            states: List of completed pipeline states.
        """
        from core.event import MemoryIngestEvent

        events: list[MemoryIngestEvent] = []
        for state in states:
            # Skip terminal states (failed processing)
            if state.get("terminal"):
                continue

            article_id = state.get("article_id")
            if not article_id:
                continue

            events.append(
                MemoryIngestEvent(
                    article_id=article_id,
                    state=dict(state),
                )
            )

        if not events:
            return

        # Outbox-first: persist before dispatching so a crash between the
        # pipeline write and event consumption cannot lose the event.
        row_ids: dict[int, int | None] = {}
        if self._outbox_repo is not None:
            for event in events:
                try:
                    row_ids[id(event)] = await self._outbox_repo.enqueue(
                        event_type=type(event).__name__,
                        payload={"article_id": event.article_id, "state": event.state},
                        article_id=event.article_id,
                    )
                except Exception as exc:
                    row_ids[id(event)] = None
                    log.error(
                        "outbox_enqueue_failed",
                        article_id=event.article_id,
                        error=str(exc),
                    )

        # Publish all events concurrently (best-effort fast path)
        results = await asyncio.gather(
            *[self._event_bus.publish(e) for e in events],
            return_exceptions=True,
        )

        for event, result in zip(events, results, strict=False):
            row_id = row_ids.get(id(event))
            if isinstance(result, Exception):
                log.warning(
                    "failed_to_publish_memory_event",
                    article_id=event.article_id,
                    error=str(result),
                )
                # keep 'pending' — the dispatcher job retries it
            else:
                log.debug("memory_ingest_event_published", article_id=event.article_id)
                if self._outbox_repo is not None and row_id is not None:
                    try:
                        await self._outbox_repo.mark_dispatched(row_id)
                    except Exception as exc:
                        log.debug("outbox_mark_dispatched_failed", error=str(exc))
