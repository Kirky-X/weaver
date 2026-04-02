# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Provider metrics for monitoring LLM operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


@dataclass
class ProviderMetrics:
    """Provider监控指标.

    跟踪请求统计、延迟、错误率等指标.
    """

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    last_request_time: float = 0.0
    last_error: str = ""
    last_error_time: float = 0.0
    _lock: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        import asyncio

        object.__setattr__(self, "_lock", asyncio.Lock())

    @property
    def success_rate(self) -> float:
        """成功率（0.0 - 1.0）."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def failure_rate(self) -> float:
        """失败率（0.0 - 1.0）."""
        return 1.0 - self.success_rate

    @property
    def avg_latency_ms(self) -> float:
        """平均延迟（毫秒）."""
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    async def record_success(self, latency_ms: float) -> None:
        """记录成功调用.

        Args:
            latency_ms: 调用延迟（毫秒）
        """
        async with self._lock:
            self.total_requests += 1
            self.successful_requests += 1
            self.total_latency_ms += latency_ms
            self.last_request_time = monotonic()

    async def record_failure(self, error: str) -> None:
        """记录失败调用.

        Args:
            error: 错误信息
        """
        async with self._lock:
            self.total_requests += 1
            self.failed_requests += 1
            self.last_error = error
            self.last_error_time = monotonic()

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "last_error": self.last_error,
        }

    def reset(self) -> None:
        """重置所有指标."""
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_latency_ms = 0.0
        self.last_request_time = 0.0
        self.last_error = ""
        self.last_error_time = 0.0
