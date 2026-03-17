"""LLM Batch Aggregator for request coalescing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Type

from pydantic import BaseModel

from core.llm.types import CallPoint, LLMTask, LLMType
from core.observability.logging import get_logger

log = get_logger("batch_aggregator")


@dataclass
class BatchRequest:
    """A single request in a batch."""

    call_point: CallPoint
    payload: dict[str, Any]
    output_model: Type[BaseModel] | None
    future: asyncio.Future
    created_at: float = field(default_factory=time.monotonic)


class LLMBatchAggregator:
    """Aggregates LLM requests into batches for better throughput.

    This is particularly useful for local LLM providers (Ollama) that
    support batch inference, reducing per-request overhead.

    Args:
        window_ms: Aggregation window in milliseconds.
        max_batch_size: Maximum batch size before forcing dispatch.
        enabled_call_points: Set of call points to aggregate (None = all).
    """

    def __init__(
        self,
        window_ms: int = 100,
        max_batch_size: int = 8,
        enabled_call_points: set[CallPoint] | None = None,
    ) -> None:
        self._window_ms = window_ms
        self._max_batch_size = max_batch_size
        self._enabled_call_points = enabled_call_points
        self._pending: dict[CallPoint, list[BatchRequest]] = {}
        self._timers: dict[CallPoint, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._started = False

    def is_enabled_for(self, call_point: CallPoint) -> bool:
        """Check if batching is enabled for a call point."""
        if self._enabled_call_points is None:
            return True
        return call_point in self._enabled_call_points

    async def start(self) -> None:
        """Start the aggregator."""
        self._started = True
        log.info(
            "batch_aggregator_started",
            window_ms=self._window_ms,
            max_batch_size=self._max_batch_size,
        )

    async def stop(self) -> None:
        """Stop the aggregator and process remaining requests."""
        self._started = False
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        for call_point, requests in self._pending.items():
            if requests:
                await self._dispatch_batch(call_point)
        log.info("batch_aggregator_stopped")

    async def submit(
        self,
        call_point: CallPoint,
        payload: dict[str, Any],
        output_model: Type[BaseModel] | None = None,
    ) -> Any:
        """Submit a request for potential batching.

        Args:
            call_point: The pipeline stage making the call.
            payload: Data to send to the LLM.
            output_model: Optional Pydantic model for structured output.

        Returns:
            The result from the LLM call.
        """
        if not self._started or not self.is_enabled_for(call_point):
            return None

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        request = BatchRequest(
            call_point=call_point,
            payload=payload,
            output_model=output_model,
            future=future,
        )

        async with self._lock:
            if call_point not in self._pending:
                self._pending[call_point] = []
                self._timers[call_point] = asyncio.create_task(
                    self._timer_dispatch(call_point)
                )

            self._pending[call_point].append(request)

            if len(self._pending[call_point]) >= self._max_batch_size:
                asyncio.create_task(self._dispatch_batch(call_point))

        return await future

    async def _timer_dispatch(self, call_point: CallPoint) -> None:
        """Dispatch batch after window expires."""
        await asyncio.sleep(self._window_ms / 1000.0)
        async with self._lock:
            if call_point in self._pending and self._pending[call_point]:
                await self._dispatch_batch(call_point)

    async def _dispatch_batch(self, call_point: CallPoint) -> None:
        """Dispatch a batch of requests."""
        async with self._lock:
            requests = self._pending.pop(call_point, [])
            self._timers.pop(call_point, None)

        if not requests:
            return

        log.debug(
            "batch_dispatch",
            call_point=call_point.value,
            batch_size=len(requests),
        )

        for request in requests:
            if not request.future.done():
                request.future.set_exception(
                    RuntimeError("Batch aggregator not connected to LLM")
                )

    def get_stats(self) -> dict[str, Any]:
        """Get aggregator statistics."""
        return {
            "started": self._started,
            "pending_batches": len(self._pending),
            "pending_requests": sum(len(r) for r in self._pending.values()),
            "window_ms": self._window_ms,
            "max_batch_size": self._max_batch_size,
        }
