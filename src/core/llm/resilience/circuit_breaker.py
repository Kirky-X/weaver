# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Circuit breaker wrapper using pybreaker.

ProviderCircuitBreaker wraps pybreaker for LLM provider-level circuit breaking.
For the unified implementation with event emission and metrics, see:
    core/resilience/circuit_breaker.py  (CircuitBreaker class)

NOTE: pybreaker's call_async is designed for Tornado @gen.coroutine,
not native Python async/await. We implement manual async handling here.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import Any

from pybreaker import CircuitBreaker as PyBreaker, CircuitBreakerError as PyCircuitBreakerError

from core.llm.types import CircuitState
from core.observability import get_logger

log = get_logger(__name__)


class CircuitOpenError(Exception):
    """熔断器开启异常."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"Circuit breaker is OPEN for provider: {provider}")


class ProviderCircuitBreaker:
    """基于pybreaker的熔断器封装.

    提供异步调用支持和状态查询.
    支持慢请求追踪: 连续慢请求会降低 editorial 分数.

    Implements: CircuitBreaker (for ModelSelector)

    For event-emitting variant, use CircuitBreaker from core/resilience/circuit_breaker.py.
    """

    def __init__(
        self,
        name: str,
        fail_max: int = 5,
        reset_timeout: float = 60.0,
        exclude_exceptions: list[type[Exception]] | None = None,
        slow_threshold: float = 0.5,
    ) -> None:
        self.name = name
        self._breaker = PyBreaker(
            name=name,
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            exclude=exclude_exceptions or [],
        )
        self._slow_threshold = slow_threshold
        self._consecutive_slow = 0
        self._timeout: float = 120.0
        # Self-maintained counters to avoid pybreaker private _state_storage API
        self._failure_counter: int = 0
        self._success_counter: int = 0
        # Monotonic timestamp when the circuit last entered OPEN state.
        # pybreaker's OPEN→HALF_OPEN transition fires only inside
        # ``CircuitOpenState.before_call`` (i.e., via ``self._breaker.call()``),
        # but this wrapper calls ``func`` directly, so we replicate the timeout
        # check here using a self-maintained timestamp.
        self._opened_at: float | None = None

    @property
    def slow_count(self) -> int:
        return self._consecutive_slow

    def mark_slow(self) -> None:
        self._consecutive_slow += 1
        if self._consecutive_slow >= 5:
            log.warning(
                "circuit_slow_degraded",
                provider=self.name,
                consecutive=self._consecutive_slow,
            )

    def mark_fast(self) -> None:
        self._consecutive_slow = 0

    @property
    def is_slow(self) -> bool:
        return self._consecutive_slow >= 5

    def _can_attempt_reset(self) -> bool:
        """Return True if ``reset_timeout`` has elapsed since the circuit opened.

        pybreaker would normally perform this check inside
        ``CircuitOpenState.before_call`` when ``self._breaker.call()`` is
        invoked. Because this wrapper calls ``func`` directly, the check is
        replicated here so the OPEN→HALF_OPEN transition still fires.
        """
        if self._opened_at is None:
            return False
        return (time.monotonic() - self._opened_at) >= self._breaker.reset_timeout

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._breaker.current_state == "open":
            if self._can_attempt_reset():
                self._breaker.half_open()
                log.info(
                    "circuit_half_open_after_timeout",
                    provider=self.name,
                    reset_timeout=self._breaker.reset_timeout,
                )
            else:
                log.warning("circuit_open", provider=self.name)
                raise CircuitOpenError(self.name)

        try:
            start = time.monotonic()
            result = await func(*args, **kwargs)
            elapsed = (time.monotonic() - start) * 1000

            threshold_ms = self._timeout * self._slow_threshold * 1000
            if elapsed >= threshold_ms:
                self.mark_slow()
            else:
                self.mark_fast()

            self._handle_success()
            return result

        except PyCircuitBreakerError:
            log.warning("circuit_open_during_call", provider=self.name)
            raise CircuitOpenError(self.name) from None
        except Exception as e:
            self._handle_failure()
            log.error(
                "circuit_failure_recorded",
                provider=self.name,
                error=str(e),
                fail_counter=self._failure_counter,
            )
            raise

    def _handle_success(self) -> None:
        # Self-maintained counters avoid pybreaker's private _state_storage API
        if self._breaker.current_state == "half-open":
            self._success_counter += 1
            if self._success_counter >= self._breaker.success_threshold:
                self._success_counter = 0
                self._failure_counter = 0
                self._opened_at = None
                self._breaker.close()
                log.info("circuit_closed_after_success", provider=self.name)
        else:
            # In closed state, reset counters on success
            self._success_counter = 0
            self._failure_counter = 0
            self._breaker.close()

    def _handle_failure(self) -> None:
        # In half-open state, any failure re-opens the circuit immediately,
        # mirroring pybreaker's CircuitHalfOpenState.on_failure.
        if self._breaker.current_state == "half-open":
            self._failure_counter = 0
            self._success_counter = 0
            self._opened_at = time.monotonic()
            self._breaker.open()
            log.error(
                "circuit_reopened_after_half_open_failure",
                provider=self.name,
            )
            return

        # Self-maintained counter avoids pybreaker's private _state_storage API
        self._failure_counter += 1
        if self._failure_counter >= self._breaker.fail_max:
            self._failure_counter = 0
            self._success_counter = 0
            self._opened_at = time.monotonic()
            self._breaker.open()
            log.error(
                "circuit_opened_after_failures",
                provider=self.name,
                fail_max=self._breaker.fail_max,
            )
        else:
            log.warning(
                "circuit_failure_recorded",
                provider=self.name,
                fail_counter=self._failure_counter,
                fail_max=self._breaker.fail_max,
            )

    def record_success(self) -> None:
        self._handle_success()

    def record_failure(self) -> None:
        self._handle_failure()

    @property
    def is_open(self) -> bool:
        # ``current_state`` is the raw storage state and does not trigger the
        # OPEN→HALF_OPEN transition. We surface a False ``is_open`` once
        # ``reset_timeout`` has elapsed so callers (e.g. ProviderPool.execute)
        # route the next call into ``call()``, which performs the actual
        # half_open() transition.
        if self._breaker.current_state != "open":
            return False
        return not self._can_attempt_reset()

    @property
    def state(self) -> CircuitState:
        state_map = {
            "closed": CircuitState.CLOSED,
            "open": CircuitState.OPEN,
            "half-open": CircuitState.HALF_OPEN,
        }
        return state_map.get(self._breaker.current_state, CircuitState.CLOSED)

    def reset(self) -> None:
        with contextlib.suppress(Exception):
            self._breaker.close()
        self._consecutive_slow = 0
        self._opened_at = None

    def __repr__(self) -> str:
        return f"ProviderCircuitBreaker(name={self.name!r}, state={self.state.value}, slow={self._consecutive_slow})"
