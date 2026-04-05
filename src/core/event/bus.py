# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Internal event bus for decoupled component communication.

Uses blinker for signal dispatching while maintaining a type-safe API.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from blinker import Signal

from core.llm.types import TokenUsage
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
class PipelineStageCompletedEvent(BaseEvent):
    """Emitted when a pipeline stage completes."""

    stage: str = ""
    article_url: str = ""
    latency_ms: float = 0.0


@dataclass
class LLMFailureEvent(BaseEvent):
    """Emitted when all providers in the fallback chain have failed for an LLM call."""

    call_point: str = ""
    provider: str = ""
    error_type: str = ""
    error_detail: str = ""
    latency_ms: float = 0.0
    article_id: str | None = None
    task_id: str | None = None
    attempt: int = 0
    fallback_tried: bool = False


@dataclass
class LLMUsageEvent(BaseEvent):
    """LLM 调用用量事件，用于统计和监控 LLM 资源消耗。

    Attributes:
        label: 调用标签 (type.provider.model 格式，如 "chat::aiping::qwen-plus")
        call_point: 调用点标识 (pipeline 节点名)
        llm_type: LLM 类型 (chat/embedding/rerank)
        provider: LLM 提供商名称
        model: 使用的模型名称
        tokens: Token 使用量统计
        latency_ms: 调用延迟（毫秒）
        success: 调用是否成功
        error_type: 错误类型（失败时）
        article_id: 关联的文章 ID
        task_id: 关联的任务 ID
    """

    label: str = ""
    call_point: str = ""
    llm_type: str = ""
    provider: str = ""
    model: str = ""
    tokens: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    success: bool = True
    error_type: str | None = None
    article_id: int | None = None
    task_id: str | None = None


# ── Event Bus (Blinker-backed) ────────────────────────────────────────

EventHandler = Callable[[Any], Coroutine[Any, Any, None]]


class EventBus:
    """Async event bus using blinker for signal dispatching.

    Maintains the same API as the previous dict-based implementation,
    but uses blinker.Signal under the hood for standard signal handling.

    Handlers are registered per event type and invoked concurrently
    when an event is published.
    """

    def __init__(self) -> None:
        # Map event types to blinker Signals
        self._signals: dict[type, Signal] = {}
        # Store async handlers for proper dispatch
        self._handlers: dict[type, list[EventHandler]] = {}

    def _get_signal(self, event_type: type) -> Signal:
        """Get or create a Signal for an event type."""
        if event_type not in self._signals:
            signal_name = f"{event_type.__module__}.{event_type.__name__}"
            self._signals[event_type] = Signal(signal_name)
        return self._signals[event_type]

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Subscribe a handler to an event type.

        Args:
            event_type: The event class to subscribe to.
            handler: Async callable that receives the event.
        """
        self._handlers.setdefault(event_type, []).append(handler)

        # Also connect to blinker signal for potential external use
        signal = self._get_signal(event_type)

        # Create a sync wrapper that the signal can call
        def sync_wrapper(sender: Any, **kwargs: Any) -> None:
            # This won't await - just for blinker compatibility
            # Actual async dispatch happens in publish()
            pass

        signal.connect(sync_wrapper, sender=event_type)

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

        # Send via blinker for any sync listeners
        signal = self._get_signal(event_type)
        signal.send(event_type, event=event)

        # Dispatch to async handlers concurrently
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
