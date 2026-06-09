# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Circuit breaker wrapper using pybreaker.

This module provides backward-compatible ProviderCircuitBreaker wrapping pybreaker.
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
from core.observability.logging import get_logger

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

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if self._breaker.current_state == "open":
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
                fail_counter=self._breaker.fail_counter,
            )
            raise

    def _handle_success(self) -> None:
        storage = self._breaker._state_storage
        if self._breaker.current_state == "half-open":
            storage.increment_success_counter()
            if self._breaker.success_counter >= self._breaker.success_threshold:
                self._breaker.close()
                log.info("circuit_closed_after_success", provider=self.name)
        else:
            storage.reset_counter()
            self._breaker.close()

    def _handle_failure(self) -> None:
        storage = self._breaker._state_storage
        storage.increment_counter()
        if self._breaker.fail_counter >= self._breaker.fail_max:
            self._breaker.open()
            log.error(
                "circuit_opened_after_failures",
                provider=self.name,
                fail_counter=self._breaker.fail_counter,
                fail_max=self._breaker.fail_max,
            )

    def record_success(self) -> None:
        self._handle_success()

    def record_failure(self) -> None:
        self._handle_failure()

    @property
    def is_open(self) -> bool:
        return self._breaker.current_state == "open"

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

    def __repr__(self) -> str:
        return f"ProviderCircuitBreaker(name={self.name!r}, state={self.state.value}, slow={self._consecutive_slow})"
