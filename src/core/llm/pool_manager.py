# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Provider pool manager for managing all LLM provider pools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.llm.label import Label
from core.llm.provider_pool import CircuitOpenError, ProviderPool
from core.llm.registry import ProviderInstanceConfig, ProviderRegistry
from core.llm.request import LLMRequest, LLMResponse, ProviderMetrics
from core.llm.types import LLMType
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector

if TYPE_CHECKING:

    from core.llm.rate_limiter import RedisTokenBucket

log = get_logger("pool_manager")


class NoProviderAvailableError(Exception):
    """没有可用的供应商异常。"""

    def __init__(self, label: Label, reason: str = "") -> None:
        self.label = label
        self.reason = reason
        super().__init__(f"No available provider for label '{label}': {reason}")


class AllProvidersFailedError(Exception):
    """所有供应商都失败异常。"""

    def __init__(
        self, label: Label, providers: list[str], last_error: Exception | None = None
    ) -> None:
        self.label = label
        self.providers = providers
        self.last_error = last_error
        super().__init__(
            f"All providers failed for label '{label}': {providers}. " f"Last error: {last_error}"
        )


@dataclass
class PoolManagerConfig:
    """池管理器配置。

    Attributes:
        circuit_breaker_threshold: 熔断器失败阈值
        circuit_breaker_timeout: 熔断器冷却时间（秒）
        default_timeout: 默认超时时间（秒）
        max_retries: 最大重试次数
    """

    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0
    default_timeout: float = 120.0
    max_retries: int = 3


class ProviderPoolManager:
    """供应商池管理器。

    管理：
    - 所有供应商池的生命周期
    - 供应商池的创建和销毁
    - 基于 Label 的供应商查找
    - Fallback 链管理
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        rate_limiter: RedisTokenBucket | None = None,
        config: PoolManagerConfig | None = None,
    ) -> None:
        """初始化池管理器。

        Args:
            registry: 供应商注册中心
            rate_limiter: 可选的 Redis 令牌桶限流器
            config: 池管理器配置
        """
        self._registry = registry
        self._rate_limiter = rate_limiter
        self._config = config or PoolManagerConfig()

        # 供应商池映射
        self._pools: dict[str, ProviderPool] = {}

        # Provider 名称到实例名称的映射 (用于标签查找)
        self._provider_to_instances: dict[str, list[str]] = {}

        # 默认供应商配置 (每个类型)
        self._defaults: dict[LLMType, str] = {}

    async def register_provider(self, instance_config: ProviderInstanceConfig) -> None:
        """注册供应商实例。

        Args:
            instance_config: 供应商实例配置
        """
        # 创建供应商实例
        provider = self._registry.create_provider(instance_config)

        # 创建池
        pool = ProviderPool(
            config=instance_config,
            provider=provider,
            rate_limiter=self._rate_limiter,
            circuit_breaker_threshold=self._config.circuit_breaker_threshold,
            circuit_breaker_timeout=self._config.circuit_breaker_timeout,
        )

        self._pools[instance_config.name] = pool

        # 更新 provider 到实例的映射
        provider_type = instance_config.provider_type
        if provider_type not in self._provider_to_instances:
            self._provider_to_instances[provider_type] = []
        self._provider_to_instances[provider_type].append(instance_config.name)

        log.info(
            "provider_registered",
            name=instance_config.name,
            type=provider_type,
            model=instance_config.model,
        )

    def set_default_provider(self, llm_type: LLMType, instance_name: str) -> None:
        """设置默认供应商。

        Args:
            llm_type: LLM 类型
            instance_name: 供应商实例名称
        """
        if instance_name not in self._pools:
            raise ValueError(f"Provider instance not found: {instance_name}")
        self._defaults[llm_type] = instance_name
        log.info("default_provider_set", llm_type=llm_type.value, instance=instance_name)

    async def start_all(self) -> None:
        """启动所有供应商池。"""
        for pool in self._pools.values():
            await pool.start()

        log.info("pool_manager_started", pools=list(self._pools.keys()))

    async def stop_all(self) -> None:
        """停止所有供应商池。"""
        for pool in self._pools.values():
            await pool.stop()

        log.info("pool_manager_stopped")

    async def close_all(self) -> None:
        """关闭所有供应商池并释放资源。"""
        for pool in self._pools.values():
            await pool.close()

        self._pools.clear()
        self._provider_to_instances.clear()
        self._defaults.clear()

        log.info("pool_manager_closed")

    def get_pool(self, name: str) -> ProviderPool | None:
        """获取供应商池。

        Args:
            name: 供应商实例名称

        Returns:
            供应商池或 None
        """
        return self._pools.get(name)

    def get_pool_by_label(self, label: Label) -> ProviderPool | None:
        """根据标签获取供应商池。

        首先尝试精确匹配 provider 名称，然后尝试类型匹配。

        Args:
            label: 调用标签

        Returns:
            供应商池或 None
        """
        # 1. 尝试精确匹配 provider 名称
        pool = self._pools.get(label.provider)
        if pool and pool.config.supports(label.llm_type):
            return pool

        # 2. 尝试通过 provider 类型查找
        instances = self._provider_to_instances.get(label.provider, [])
        for instance_name in instances:
            pool = self._pools.get(instance_name)
            if pool and pool.config.supports(label.llm_type):
                return pool

        # 3. 尝试使用默认供应商
        default_name = self._defaults.get(label.llm_type)
        if default_name:
            pool = self._pools.get(default_name)
            if pool:
                return pool

        return None

    async def execute(
        self,
        request: LLMRequest,
        fallback_labels: list[Label] | None = None,
    ) -> LLMResponse:
        """执行请求，支持 Fallback 链。

        Args:
            request: LLM 请求
            fallback_labels: 备用标签列表

        Returns:
            LLM 响应

        Raises:
            AllProvidersFailedError: 所有供应商都失败
        """
        # 构建标签链
        labels = [request.label]
        if fallback_labels:
            labels.extend(fallback_labels)

        last_error: Exception | None = None
        tried_providers: list[str] = []

        for idx, label in enumerate(labels):
            pool = self.get_pool_by_label(label)

            if not pool:
                log.warning(
                    "no_pool_for_label",
                    label=str(label),
                    available_pools=list(self._pools.keys()),
                )
                continue

            tried_providers.append(pool.name)

            # 检查熔断器
            if pool.health_status.value == "unhealthy":
                log.warning(
                    "provider_unhealthy",
                    pool=pool.name,
                    label=str(label),
                )
                MetricsCollector.fallback_total.labels(
                    call_point=label.llm_type.value,
                    from_provider=pool.name,
                    reason="circuit_open",
                ).inc()
                continue

            try:
                # 更新请求的标签为实际使用的标签
                actual_request = LLMRequest(
                    label=label,
                    payload=request.payload,
                    priority=request.priority,
                    timeout=request.timeout,
                    metadata=request.metadata,
                )

                response = await pool.submit(actual_request)

                # 记录 Fallback 成功
                if idx > 0:
                    log.info(
                        "fallback_success",
                        original=str(request.label),
                        actual=str(label),
                        attempt=idx,
                    )

                return response

            except CircuitOpenError:
                log.warning(
                    "circuit_open_during_execution",
                    pool=pool.name,
                    label=str(label),
                )
                continue

            except Exception as exc:
                last_error = exc
                log.error(
                    "provider_execution_failed",
                    pool=pool.name,
                    label=str(label),
                    error=str(exc),
                )

                # 记录 Fallback 事件
                MetricsCollector.fallback_total.labels(
                    call_point=label.llm_type.value,
                    from_provider=pool.name,
                    reason=type(exc).__name__,
                ).inc()

                continue

        raise AllProvidersFailedError(
            label=request.label,
            providers=tried_providers,
            last_error=last_error,
        )

    def get_all_metrics(self) -> dict[str, ProviderMetrics]:
        """获取所有供应商的指标。"""
        return {name: pool.get_metrics() for name, pool in self._pools.items()}

    def get_healthy_providers(self, llm_type: LLMType) -> list[str]:
        """获取指定类型的健康供应商列表。

        Args:
            llm_type: LLM 类型

        Returns:
            健康供应商名称列表
        """
        healthy = []
        for name, pool in self._pools.items():
            if pool.config.supports(llm_type) and pool.is_available:
                healthy.append(name)
        return healthy

    def list_providers(self) -> list[str]:
        """列出所有供应商实例。"""
        return list(self._pools.keys())
