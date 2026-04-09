# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Circuit breaker wrapper using pybreaker.

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

log = get_logger("circuit_breaker")


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
    """

    def __init__(
        self,
        name: str,
        fail_max: int = 5,
        reset_timeout: float = 60.0,
        exclude_exceptions: list[type[Exception]] | None = None,
        slow_threshold: float = 0.5,
    ) -> None:
        """初始化熔断器.

        Args:
            name: 熔断器名称（通常是provider名称）
            fail_max: 连续失败次数阈值，超过后打开熔断器
            reset_timeout: 熔断器冷却时间（秒），之后进入半开状态
            exclude_exceptions: 不计入失败的异常类型列表
            slow_threshold: 慢请求阈值（timeout 的比例，默认 0.5 表示 50%）
        """
        self.name = name
        self._breaker = PyBreaker(
            name=name,
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            exclude=exclude_exceptions or [],
        )
        self._slow_threshold = slow_threshold
        self._consecutive_slow = 0
        self._timeout: float = 120.0  # Default, updated by caller

    @property
    def slow_count(self) -> int:
        """Number of consecutive slow requests."""
        return self._consecutive_slow

    def mark_slow(self) -> None:
        """Mark a request as slow. After 5 consecutive slow requests,
        the provider's editorial score should be degraded by the selector.
        """
        self._consecutive_slow += 1
        if self._consecutive_slow >= 5:
            log.warning(
                "circuit_slow_degraded",
                provider=self.name,
                consecutive=self._consecutive_slow,
            )

    def mark_fast(self) -> None:
        """Mark a request as fast, resetting the slow counter."""
        self._consecutive_slow = 0

    @property
    def is_slow(self) -> bool:
        """Whether this provider has consecutive slow requests."""
        return self._consecutive_slow >= 5

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """通过熔断器执行异步函数.

        手动实现async支持，因为pybreaker的call_async是Tornado专用.

        Args:
            func: 要执行的异步函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果

        Raises:
            CircuitOpenError: 熔断器处于开启状态
            Exception: 函数执行过程中的异常
        """
        # 检查熔断器状态
        if self._breaker.current_state == "open":
            log.warning("circuit_open", provider=self.name)
            raise CircuitOpenError(self.name)

        try:
            # Track latency for slow request detection
            start = time.monotonic()
            result = await func(*args, **kwargs)
            elapsed = (time.monotonic() - start) * 1000  # ms

            # Check if slow
            threshold_ms = self._timeout * self._slow_threshold * 1000
            if elapsed >= threshold_ms:
                self.mark_slow()
            else:
                self.mark_fast()

            # 成功时记录(重置失败计数器,半开状态→关闭)
            self._record_success()
            return result

        except PyCircuitBreakerError:
            log.warning("circuit_open_during_call", provider=self.name)
            raise CircuitOpenError(self.name) from None
        except Exception as e:
            # 失败时递增计数器,达到阈值则打开熔断器
            self._record_failure()
            log.error(
                "circuit_failure_recorded",
                provider=self.name,
                error=str(e),
                fail_counter=self._breaker.fail_counter,
            )
            raise

    def _record_success(self) -> None:
        """记录成功调用.

        使用pybreaker内部state_storage操作计数器.
        半开状态下达到success_threshold后关闭熔断器.
        """
        storage = self._breaker._state_storage
        if self._breaker.current_state == "half-open":
            storage.increment_success_counter()
            if self._breaker.success_counter >= self._breaker.success_threshold:
                self._breaker.close()
                log.info("circuit_closed_after_success", provider=self.name)
        else:
            # closed状态: 重置失败计数器
            storage.reset_counter()

    def _record_failure(self) -> None:
        """记录失败调用.

        使用pybreaker内部state_storage递增失败计数器.
        达到fail_max阈值则打开熔断器.
        """
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
        """记录成功调用（半开状态下使用）."""
        self._record_success()

    def record_failure(self) -> None:
        """记录失败调用."""
        self._record_failure()

    @property
    def is_open(self) -> bool:
        """熔断器是否开启."""
        return self._breaker.current_state == "open"

    @property
    def state(self) -> CircuitState:
        """获取熔断器状态."""
        state_map = {
            "closed": CircuitState.CLOSED,
            "open": CircuitState.OPEN,
            "half-open": CircuitState.HALF_OPEN,
        }
        return state_map.get(self._breaker.current_state, CircuitState.CLOSED)

    def reset(self) -> None:
        """重置熔断器状态."""
        with contextlib.suppress(Exception):
            self._breaker.close()
        self._consecutive_slow = 0

    def __repr__(self) -> str:
        return f"ProviderCircuitBreaker(name={self.name!r}, state={self.state.value}, slow={self._consecutive_slow})"
