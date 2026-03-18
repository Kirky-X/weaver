# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM Queue Manager with Fallback Chain and priority queuing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from core.event.bus import EventBus, FallbackEvent
from core.llm.config_manager import LLMConfigManager
from core.llm.providers.base import BaseLLMProvider
from core.llm.rate_limiter import RedisTokenBucket
from core.llm.types import CallPoint, LLMTask
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from core.resilience.circuit_breaker import CircuitBreaker

log = get_logger("queue_manager")

FALLBACK_ERRORS = (TimeoutError, ConnectionError, OSError)
RETRY_ERRORS = ("APITimeoutError", "OutputParserException")
SELF_RETRY_ERRORS = ("OutputParserException",)
NON_RETRYABLE_STATUS = {400, 401, 403, 413}
MAX_RETRIES = 2
RETRY_DELAY_BASE = 5

HEALTH_CHECK_INTERVAL = 30
HEALTH_CHECK_TIMEOUT = 10


@dataclass
class ProviderHealth:
    """Health metrics for a provider.

    Attributes:
        success_count: Total successful calls.
        failure_count: Total failed calls.
        avg_latency_ms: Rolling average latency in milliseconds.
        last_success: Timestamp of last successful call.
        last_failure: Timestamp of last failed call.
    """

    success_count: int = 0
    failure_count: int = 0
    avg_latency_ms: float = 0.0
    last_success: float = 0.0
    last_failure: float = 0.0

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0 to 1.0)."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total

    def record_success(self, latency_ms: float) -> None:
        """Record a successful call."""
        self.success_count += 1
        self.last_success = time.monotonic()
        if self.avg_latency_ms == 0:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = 0.9 * self.avg_latency_ms + 0.1 * latency_ms

    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure = time.monotonic()


class AllProvidersFailedError(Exception):
    """Raised when all providers in the fallback chain have failed."""

    def __init__(self, call_point: CallPoint, providers: list) -> None:
        self.call_point = call_point
        self.providers = providers
        super().__init__(
            f"All providers failed for {call_point}: "
            f"{[getattr(p, 'provider', str(p)) for p in providers]}"
        )


class ProviderQueue:
    """Priority queue for a single LLM provider with concurrency control."""

    def __init__(
        self,
        provider_name: str,
        concurrency: int,
        provider: BaseLLMProvider,
    ) -> None:
        self.name = provider_name
        self._provider = provider
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(concurrency)
        self.circuit_breaker = CircuitBreaker()
        self._workers: list[asyncio.Task] = []

    async def enqueue(self, task: LLMTask) -> asyncio.Future:
        """Add a task to the queue and return a future for the result."""
        task.future = asyncio.get_running_loop().create_future()
        await self._queue.put((task.priority, id(task), task))
        return task.future

    async def start_workers(self, n: int) -> None:
        """Start n worker tasks processing the queue."""
        for _ in range(n):
            worker = asyncio.create_task(self._worker())
            self._workers.append(worker)

    async def stop_workers(self) -> None:
        """Cancel all worker tasks."""
        for worker in self._workers:
            worker.cancel()
        self._workers.clear()

    async def _worker(self) -> None:
        """Worker loop: dequeue tasks and dispatch to the provider."""
        while True:
            try:
                _, _, task = await self._queue.get()
                async with self._semaphore:
                    try:
                        result = await self._dispatch(task)
                        self.circuit_breaker.record_success()
                        if not task.future.done():
                            task.future.set_result(result)
                    except Exception as exc:
                        self.circuit_breaker.record_failure()
                        if not task.future.done():
                            task.future.set_exception(exc)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("worker_unexpected_error", provider=self.name, error=str(exc))

    async def _dispatch(self, task: LLMTask) -> str:
        """Dispatch a task to the underlying LLM provider."""
        import time

        start = time.monotonic()
        try:
            result = await self._provider.chat(
                system_prompt=task.payload.get("system_prompt", ""),
                user_content=task.payload.get("user_content", ""),
            )
            latency = time.monotonic() - start
            MetricsCollector.llm_call_total.labels(
                call_point=task.call_point.value,
                provider=self.name,
                status="success",
            ).inc()
            log.info(
                "llm_call_success",
                call_point=task.call_point.value,
                provider=self.name,
                latency=latency,
            )
            return result
        except Exception as exc:
            latency = time.monotonic() - start
            log.error(
                "llm_dispatch_failed",
                call_point=task.call_point.value,
                provider=self.name,
                error=type(exc).__name__,
                error_detail=str(exc),
                latency=latency,
            )
            raise


class LLMQueueManager:
    """Manages multiple provider queues with fallback chain support.

    Implements:
    - Priority-based queue per provider
    - Circuit breaker per provider
    - Redis token bucket rate limiting
    - Automatic fallback to next provider on failure
    - Self-retry for OutputParserException
    """

    def __init__(
        self,
        config_manager: LLMConfigManager,
        rate_limiter: RedisTokenBucket | ProRateLimiter,
        event_bus: EventBus,
    ) -> None:
        self._config = config_manager
        self._rate_limiter = rate_limiter
        self._event_bus = event_bus
        self._queues: dict[str, ProviderQueue] = {}
        self._providers: dict[str, BaseLLMProvider] = {}

    async def startup(self) -> None:
        """Initialize provider queues and start workers."""
        from core.llm.providers.anthropic import AnthropicProvider
        from core.llm.providers.chat import ChatProvider
        from core.llm.providers.embedding import EmbeddingProvider

        for name, cfg in self._config.list_providers():
            if cfg.provider == "anthropic":
                provider: BaseLLMProvider = AnthropicProvider(
                    api_key=cfg.api_key,
                    base_url=cfg.base_url,
                    model=cfg.model,
                    timeout=cfg.timeout,
                )
            else:
                provider = ChatProvider(
                    api_key=cfg.api_key,
                    base_url=cfg.base_url,
                    model=cfg.model,
                    timeout=cfg.timeout,
                )
            self._providers[name] = provider

            queue = ProviderQueue(name, cfg.concurrency, provider)
            await queue.start_workers(cfg.concurrency)
            self._queues[name] = queue

        # Initialize embedding provider if configured
        embedding_config = self._config.get_embedding_config()
        if embedding_config:
            provider_name, model, cfg = embedding_config
            if provider_name in self._providers:
                # Reuse the same config but as embedding provider
                self._providers[f"{provider_name}_embedding"] = EmbeddingProvider(
                    api_key=cfg.api_key,
                    base_url=cfg.base_url,
                    model=model,
                    timeout=cfg.timeout,
                )
                log.info(
                    "embedding_provider_initialized",
                    provider=provider_name,
                    model=model,
                )
            else:
                log.warning(
                    "embedding_provider_not_found",
                    provider=provider_name,
                )
        else:
            log.warning("no_embedding_configured")

        log.info("queue_manager_started", providers=list(self._queues.keys()))

    async def shutdown(self) -> None:
        """Stop all workers and close providers."""
        for queue in self._queues.values():
            await queue.stop_workers()
        for provider in self._providers.values():
            await provider.close()
        log.info("queue_manager_stopped")

    async def enqueue(self, task: LLMTask) -> Any:
        """Submit a task with fallback chain support.

        Tries the primary provider first, then each fallback in order.
        Implements self-retry for OutputParserException and circuit breaker
        bypass.

        Args:
            task: The LLM task to execute.

        Returns:
            The LLM response.

        Raises:
            AllProvidersFailedError: If all providers fail.
        """
        call_cfg = self._config.get_call_point_config(task.call_point)
        provider_chain_names = [call_cfg.primary_name] + call_cfg.fallback_names
        provider_chain_configs = [call_cfg.primary] + call_cfg.fallbacks
        last_exc: Exception | None = None

        for idx, (pcfg_name, pcfg) in enumerate(zip(provider_chain_names, provider_chain_configs)):
            queue = self._queues.get(pcfg_name)
            if not queue:
                log.warning("provider_queue_not_found", provider=pcfg_name)
                continue

            # Circuit breaker check
            if queue.circuit_breaker.is_open():
                await self._event_bus.publish(
                    FallbackEvent(
                        call_point=task.call_point.value,
                        from_provider=pcfg_name,
                        reason="circuit_open",
                        attempt=idx,
                    )
                )
                MetricsCollector.fallback_total.labels(
                    call_point=task.call_point.value,
                    from_provider=pcfg_name,
                    reason="circuit_open",
                ).inc()
                continue

            # Token bucket rate limiting (skip if rpm_limit <= 0)
            if pcfg.rpm_limit > 0:
                wait = await self._rate_limiter.consume(pcfg_name, pcfg.rpm_limit)
                if wait > 0:
                    await asyncio.sleep(wait)

            try:
                task.provider_cfg = pcfg
                future = await queue.enqueue(task)
                result = await future

                if idx > 0:
                    await self._event_bus.publish(
                        FallbackEvent(
                            call_point=task.call_point.value,
                            from_provider=provider_chain_names[0],
                            to_provider=pcfg_name,
                            reason="fallback_success",
                            attempt=idx,
                        )
                    )
                return result

            except Exception as exc:
                exc_name = type(exc).__name__

                # Log detailed error info
                log.error(
                    "llm_call_failed",
                    call_point=task.call_point.value,
                    provider=pcfg_name,
                    error=exc_name,
                    error_detail=str(exc),
                )

                # Retry logic for timeout and transient errors
                if exc_name in RETRY_ERRORS and task.attempt < MAX_RETRIES:
                    task.attempt += 1
                    retry_delay = RETRY_DELAY_BASE * (2**task.attempt)  # Exponential backoff
                    log.warning(
                        "llm_retry",
                        call_point=task.call_point.value,
                        provider=pcfg_name,
                        attempt=task.attempt,
                        delay=retry_delay,
                        error=exc_name,
                    )
                    await asyncio.sleep(retry_delay)
                    # Re-enqueue the task for retry
                    retry_future = await queue.enqueue(task)
                    try:
                        return await retry_future
                    except Exception as retry_exc:
                        log.error(
                            "llm_retry_failed",
                            call_point=task.call_point.value,
                            provider=pcfg_name,
                            attempt=task.attempt,
                            error=type(retry_exc).__name__,
                        )
                        exc = retry_exc

                # Self-retry for OutputParserException
                if exc_name in SELF_RETRY_ERRORS and task.attempt == 0:
                    task.attempt += 1
                    task.payload["_retry_hint"] = "请严格按 JSON 格式输出，不要有任何额外文字。"
                    retry_future = await queue.enqueue(task)
                    try:
                        return await retry_future
                    except Exception as retry_exc:
                        exc = retry_exc

                # Non-retryable errors
                if getattr(exc, "status_code", None) in NON_RETRYABLE_STATUS:
                    raise

                last_exc = exc
                await self._event_bus.publish(
                    FallbackEvent(
                        call_point=task.call_point.value,
                        from_provider=pcfg_name,
                        reason=exc_name,
                        attempt=idx,
                    )
                )
                MetricsCollector.fallback_total.labels(
                    call_point=task.call_point.value,
                    from_provider=pcfg_name,
                    reason=exc_name,
                ).inc()
                continue

        raise AllProvidersFailedError(task.call_point, provider_chain_names) from last_exc
