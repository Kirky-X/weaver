# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Memory event publisher collaborator.

Publishes ``MemoryIngestEvent`` for successfully processed articles so the
MAGMA memory subsystem can ingest them.

Extracted from ``Pipeline`` to keep the orchestrator focused on flow control.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.event import EventBus

log = get_logger(__name__)


class MemoryEventPublisher:
    """Publish memory ingest events for completed articles.

    Single responsibility: build ``MemoryIngestEvent`` instances from
    non-terminal pipeline states and publish them concurrently on the event
    bus, logging any per-event failures without aborting the batch.

    Args:
        event_bus: Event bus used to publish memory ingest events.
    """

    def __init__(self, *, event_bus: EventBus) -> None:
        self._event_bus = event_bus

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

        # Publish all events concurrently
        results = await asyncio.gather(
            *[self._event_bus.publish(e) for e in events],
            return_exceptions=True,
        )

        for event, result in zip(events, results, strict=False):
            if isinstance(result, Exception):
                log.warning(
                    "failed_to_publish_memory_event",
                    article_id=event.article_id,
                    error=str(result),
                )
            else:
                log.debug("memory_ingest_event_published", article_id=event.article_id)
