# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Provider pool for managing a single LLM provider's resources."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aiolimiter import AsyncLimiter

from core.llm.caller import LiteLLMCaller
from core.llm.circuit_breaker import CircuitOpenError, ProviderCircuitBreaker
from core.llm.metrics import ProviderMetrics
from core.llm.types import Label, LLMResponse, ProviderConfig
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.event.bus import EventBus

log = get_logger("provider_pool")


class AllProvidersFailedError(Exception):
    """所有provider都失败异常."""

    def __init__(
        self,
        labels: list[Label],
        last_error: Exception | None = None,
    ) -> None:
        self.labels = labels
        self.last_error = last_error
        super().__init__(
            f"All providers failed for labels: {[str(lbl) for lbl in labels]}. Last error: {last_error}"
        )


class ProviderPool:
    """单个Provider的资源池.

    管理：
    - 熔断器 (pybreaker)
    - 速率限制 (aiolimiter)
    - 并发控制 (asyncio.Semaphore)
    - 健康状态和监控指标
    """

    def __init__(
        self,
        config: ProviderConfig,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
        event_bus: EventBus | None = None,
    ) -> None:
        """初始化Provider池.

        Args:
            config: Provider配置
            circuit_breaker_threshold: 熔断器失败阈值
            circuit_breaker_timeout: 熔断器冷却时间
            event_bus: 可选的EventBus，用于发射LLMUsageEvent
        """
        self.config = config
        self.name = config.name

        # LiteLLM调用器
        self._caller = LiteLLMCaller()

        # 熔断器
        self._circuit_breaker = ProviderCircuitBreaker(
            name=config.name,
            fail_max=circuit_breaker_threshold,
            reset_timeout=circuit_breaker_timeout,
        )

        # 速率限制器
        self._rate_limiter: AsyncLimiter | None = None
        if config.rpm_limit > 0:
            self._rate_limiter = AsyncLimiter(config.rpm_limit, 60.0)

        # 并发控制
        self._semaphore = asyncio.Semaphore(config.concurrency)

        # 监控指标
        self._metrics = ProviderMetrics()

    @property
    def is_available(self) -> bool:
        """检查provider是否可用."""
        return not self._circuit_breaker.is_open

    @property
    def health_status(self) -> str:
        """获取健康状态."""
        if self._circuit_breaker.is_open:
            return "unhealthy"
        if self._metrics.success_rate < 0.5:
            return "degraded"
        return "healthy"

    async def execute(
        self,
        labels: list[Label],
        payload: dict[str, Any],
        timeout: float | None = None,
    ) -> LLMResponse:
        """执行请求，支持fallback链.

        按顺序尝试labels中的每个label，直到成功或全部失败.

        Args:
            labels: 标签链 [primary, fallback1, ...]
            payload: 调用参数
            timeout: 超时覆盖

        Returns:
            LLM响应

        Raises:
            AllProvidersFailedError: 所有provider都失败
        """
        last_error: Exception | None = None

        for idx, label in enumerate(labels):
            # 检查是否有对应的模型配置(通过model_id匹配)
            model_cfg = None
            for cfg in self.config.models.values():
                if cfg.model_id == label.model:
                    model_cfg = cfg
                    break

            if not model_cfg:
                log.warning(
                    "model_not_found",
                    provider=self.name,
                    model=label.model,
                )
                continue

            # 检查模型是否支持该类型
            if not model_cfg.supports(label.llm_type):
                log.warning(
                    "model_type_not_supported",
                    provider=self.name,
                    model=label.model,
                    llm_type=label.llm_type.value,
                )
                continue

            # 检查熔断器
            if self._circuit_breaker.is_open:
                log.warning(
                    "circuit_open",
                    provider=self.name,
                    label=str(label),
                )
                continue

            try:
                response = await self._execute_single(
                    label=label,
                    payload=payload,
                    timeout=timeout or self.config.timeout,
                )

                # 记录fallback成功
                if idx > 0:
                    log.info(
                        "fallback_success",
                        original=str(labels[0]),
                        actual=str(label),
                        attempt=idx,
                    )

                return response

            except CircuitOpenError:
                log.warning(
                    "circuit_open_during_execution",
                    provider=self.name,
                    label=str(label),
                )
                continue

            except Exception as e:
                last_error = e
                log.error(
                    "provider_execution_failed",
                    provider=self.name,
                    label=str(label),
                    error=str(e),
                )
                continue

        raise AllProvidersFailedError(labels, last_error)

    async def _execute_single(
        self,
        label: Label,
        payload: dict[str, Any],
        timeout: float,
    ) -> LLMResponse:
        """执行单个请求."""
        # 速率限制
        if self._rate_limiter:
            async with self._rate_limiter:
                pass

        # 并发控制
        async with self._semaphore:
            try:
                response = await self._circuit_breaker.call(
                    self._caller.call,
                    label=label,
                    provider_type=self.config.type,
                    api_key=self.config.api_key,
                    api_base=self.config.base_url,
                    payload=payload,
                    timeout=timeout,
                )

                await self._metrics.record_success(response.latency_ms)
                return response

            except Exception as e:
                await self._metrics.record_failure(str(e))
                raise

    def get_metrics(self) -> dict[str, Any]:
        """获取监控指标."""
        return self._metrics.to_dict()

    def reset_circuit_breaker(self) -> None:
        """重置熔断器."""
        self._circuit_breaker.reset()
