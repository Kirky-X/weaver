# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Provider pool for managing a single LLM provider's resources."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from aiolimiter import AsyncLimiter

from core.llm.caller import LiteLLMCaller
from core.llm.resilience.circuit_breaker import CircuitOpenError, ProviderCircuitBreaker
from core.llm.resilience.metrics import ProviderMetrics
from core.llm.types import GlobalConfig, Label, LLMResponse, ProviderConfig
from core.observability.logging import get_logger
from core.resilience.retry import retry_llm

if TYPE_CHECKING:
    from core.event.bus import EventBus

log = get_logger(__name__)


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
            f"All providers failed for labels: {[str(lbl) for lbl in labels]}. Last error: {last_error}",
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
        event_bus: EventBus,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
        global_config: GlobalConfig | None = None,
    ) -> None:
        """初始化Provider池.

        Args:
            config: Provider配置
            event_bus: 事件总线(必需)
            circuit_breaker_threshold: 熔断器失败阈值
            circuit_breaker_timeout: 熔断器冷却时间
            global_config: 全局配置（用于请求延迟）
        """
        self.config = config
        self.name = config.name
        self._event_bus = event_bus

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

        # 请求延迟器(类型注解)
        self._request_delay: Any = None

        # Set timeout on circuit breaker for slow request detection
        self._circuit_breaker._timeout = config.timeout

        # 初始化请求延迟器
        self._init_request_delay(config, global_config)

    @property
    def circuit_breaker(self) -> ProviderCircuitBreaker:
        """Access the circuit breaker for ModelSelector integration."""
        return self._circuit_breaker

    def _init_request_delay(
        self,
        config: ProviderConfig,
        global_config: GlobalConfig | None,
    ) -> None:
        """初始化请求延迟控制器."""
        from core.llm.resilience.request_delay import RequestDelay

        # 优先使用provider配置,回退到全局配置
        enabled = config.request_delay_enabled
        if enabled is None and global_config:
            enabled = global_config.request_delay_enabled

        delay_min = config.request_delay_min
        if delay_min is None and global_config:
            delay_min = global_config.request_delay_min

        delay_max = config.request_delay_max
        if delay_max is None and global_config:
            delay_max = global_config.request_delay_max

        self._request_delay = RequestDelay(
            enabled=enabled or False,
            delay_min=delay_min or 1.0,
            delay_max=delay_max or 2.0,
        )

    @property
    def is_available(self) -> bool:
        """检查provider是否可用."""
        return not self._circuit_breaker.is_open

    async def execute(
        self,
        labels: list[Label],
        payload: dict[str, Any],
        call_point: str,
        timeout: float | None = None,
        article_id: str | None = None,
        task_id: str | None = None,
    ) -> LLMResponse:
        """执行请求,支持fallback链.

        按顺序尝试labels中的每个label,直到成功或全部失败.

        Args:
            labels: 标签链 [primary, fallback1, ...]
            payload: 调用参数
            call_point: 调用点标识(必需)
            timeout: 超时覆盖
            article_id: 文章ID(可选)
            task_id: 任务ID(可选)

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

            # Merge model_cfg defaults into payload (call-point overrides take priority)
            merged_payload = dict(payload)
            if model_cfg.temperature is not None and "temperature" not in merged_payload:
                merged_payload["temperature"] = model_cfg.temperature
            if model_cfg.max_tokens is not None and "max_tokens" not in merged_payload:
                merged_payload["max_tokens"] = model_cfg.max_tokens
            if model_cfg.think is not None and "think" not in merged_payload:
                merged_payload["think"] = model_cfg.think

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
                    payload=merged_payload,
                    timeout=timeout or self.config.timeout,
                    call_point=call_point,
                    article_id=article_id,
                    task_id=task_id,
                    fallback_index=idx,
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
        call_point: str,
        article_id: str | None,
        task_id: str | None,
        fallback_index: int = 0,
    ) -> LLMResponse:
        """执行单个请求,带指数退避重试.

        Rate limiter在retry循环内部,确保每次重试都重新获取令牌。
        这样当429触发退避等待后,重试时rate limiter的令牌桶已有时间补充。
        """
        async with self._semaphore:
            last_error: Exception | None = None
            attempt_number = 0

            async def _call_once() -> LLMResponse:
                """单次调用：延迟 → 限流器 → 熔断器."""
                # 1. 请求延迟
                await self._request_delay.acquire(self.name)

                # 2. 限流器
                if self._rate_limiter:
                    async with self._rate_limiter:
                        return await self._do_call(label, payload, timeout)
                return await self._do_call(label, payload, timeout)

            async def _call_with_retry() -> LLMResponse:
                """Retry loop内执行实际调用,每次重试重新获取rate limiter令牌."""
                nonlocal attempt_number
                async for attempt in retry_llm(max_attempts=3, min_wait=5.0, max_wait=60.0):
                    with attempt:
                        try:
                            attempt_number += 1
                            return await _call_once()
                        except CircuitOpenError:
                            raise
                        except Exception as e:
                            nonlocal last_error
                            last_error = e
                            await self._metrics.record_failure(str(e))
                            # 发布失败事件
                            await self._emit_failure_event(
                                label=label,
                                error=e,
                                attempt=attempt_number,
                                call_point=call_point,
                                article_id=article_id,
                                task_id=task_id,
                                fallback_tried=fallback_index > 0,
                            )
                            raise

                if last_error:
                    raise last_error
                raise RuntimeError("LLM call retry exhausted")

            return await _call_with_retry()

    async def _do_call(
        self,
        label: Label,
        payload: dict[str, Any],
        timeout: float,
    ) -> LLMResponse:
        """执行实际的LLM调用,通过熔断器保护."""
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

    async def _emit_failure_event(
        self,
        label: Label,
        error: Exception,
        attempt: int,
        call_point: str,
        article_id: str | None,
        task_id: str | None,
        fallback_tried: bool,
    ) -> None:
        """发布LLM失败事件到EventBus."""
        from core.event.bus import LLMFailureEvent

        error_type = type(error).__name__
        error_detail = str(error)

        event = LLMFailureEvent(
            call_point=call_point,
            provider=self.config.name,
            error_type=error_type,
            error_detail=error_detail[:500],
            latency_ms=0.0,
            article_id=article_id,
            task_id=task_id,
            attempt=attempt,
            fallback_tried=fallback_tried,
        )
        await self._event_bus.publish(event)

    def get_metrics(self) -> dict[str, Any]:
        """获取监控指标."""
        return self._metrics.to_dict()

    def reset_circuit_breaker(self) -> None:
        """重置熔断器."""
        self._circuit_breaker.reset()
