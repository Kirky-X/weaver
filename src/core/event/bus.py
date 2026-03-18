# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Internal event bus for decoupled component communication."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.observability.logging import get_logger

log = get_logger("event_bus")


# ── Event Definitions ────────────────────────────────────────


@dataclass
class BaseEvent:
    """Base class for all domain events."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FallbackEvent(BaseEvent):
    """Emitted when an LLM call falls back to another provider."""

    call_point: str = ""
    from_provider: str = ""
    to_provider: str = ""
    reason: str = ""
    attempt: int = 0


@dataclass
class CredibilityComputedEvent(BaseEvent):
    """Emitted after credibility score is computed for an article."""

    url: str = ""
    score: float = 0.0
    cross_count: int = 0


@dataclass
class EmbeddingModelMismatchEvent(BaseEvent):
    """Emitted when embedding fallback uses a different model."""

    article_id: str = ""
    expected_model: str = ""
    actual_model: str = ""


@dataclass
class PipelineStageCompletedEvent(BaseEvent):
    """Emitted when a pipeline stage completes."""

    stage: str = ""
    article_url: str = ""
    latency_ms: float = 0.0


# ── Event Bus ────────────────────────────────────────────────

EventHandler = Callable[[Any], Coroutine[Any, Any, None]]


class EventBus:
    """Simple in-process async event bus using pub/sub pattern.

    Handlers are registered per event type and invoked concurrently
    when an event is published.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = {}

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Subscribe a handler to an event type.

        Args:
            event_type: The event class to subscribe to.
            handler: Async callable that receives the event.
        """
        self._handlers.setdefault(event_type, []).append(handler)
        log.debug(
            "event_subscribed",
            event_type=event_type.__name__,
            handler=handler.__qualname__,
        )

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all subscribed handlers.

        Handlers are called concurrently. Exceptions in individual
        handlers are logged but do not prevent other handlers from running.

        Args:
            event: The event instance to publish.
        """
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return

        log.debug(
            "event_published",
            event_type=event_type.__name__,
            handler_count=len(handlers),
        )

        tasks = [self._safe_call(handler, event) for handler in handlers]
        await asyncio.gather(*tasks)

    @staticmethod
    async def _safe_call(handler: EventHandler, event: BaseEvent) -> None:
        """Call a handler with error isolation."""
        try:
            await handler(event)
        except Exception as exc:
            log.error(
                "event_handler_failed",
                handler=handler.__qualname__,
                event_type=type(event).__name__,
                error=str(exc),
            )
