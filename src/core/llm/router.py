# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Label router for routing LLM requests based on labels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from core.llm.label import Label
from core.llm.types import LLMType
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.llm.pool_manager import ProviderPoolManager
    from core.llm.provider_pool import ProviderPool

log = get_logger("label_router")


class RoutingStrategy(str, Enum):
    """路由策略。"""

    PRIORITY = "priority"  # 按优先级排序
    WEIGHTED = "weighted"  # 加权随机
    LEAST_LATENCY = "least_latency"  # 最低延迟


@dataclass
class RoutingContext:
    """路由上下文。

    Attributes:
        llm_type: LLM 类型
        model_preference: 模型偏好
        priority_boost: 优先级提升值
    """

    llm_type: LLMType
    model_preference: str | None = None
    priority_boost: int = 0


class LabelRouter:
    """标签路由器。

    根据标签解析供应商信息，并结合路由策略选择最优供应商。

    路由流程:
    1. 解析标签 -> 提取 type/provider/model
    2. 查找匹配的供应商池
    3. 应用路由策略选择最优供应商
    4. 返回选中的供应商池
    """

    def __init__(
        self,
        pool_manager: ProviderPoolManager,
        default_strategy: RoutingStrategy = RoutingStrategy.PRIORITY,
    ) -> None:
        """初始化路由器。

        Args:
            pool_manager: 供应商池管理器
            default_strategy: 默认路由策略
        """
        self._pool_manager = pool_manager
        self._default_strategy = default_strategy

        # 调用点级别的路由配置
        self._call_point_configs: dict[str, dict[str, str | list[str]]] = {}

    def configure_call_point(
        self,
        call_point: str,
        primary_label: str,
        fallback_labels: list[str] | None = None,
    ) -> None:
        """配置调用点的路由信息。

        Args:
            call_point: 调用点名称
            primary_label: 主标签
            fallback_labels: 备用标签列表
        """
        self._call_point_configs[call_point] = {
            "primary": primary_label,
            "fallbacks": fallback_labels or [],
        }
        log.debug(
            "call_point_configured",
            call_point=call_point,
            primary=primary_label,
            fallbacks=fallback_labels,
        )

    def route(self, label: Label) -> ProviderPool | None:
        """根据标签路由到供应商池。

        路由策略:
        1. 精确匹配: 标签中的 provider 字段直接对应池名称
        2. 类型匹配: 根据 LLM 类型查找默认供应商

        Args:
            label: 调用标签

        Returns:
            选中的供应商池或 None
        """
        # 1. 精确匹配 - provider 作为池名称
        pool = self._pool_manager.get_pool(label.provider)
        if pool and pool.config.supports(label.llm_type):
            log.debug(
                "route_exact_match",
                label=str(label),
                pool=pool.name,
            )
            return pool

        # 2. 类型匹配 - 使用默认供应商
        healthy_providers = self._pool_manager.get_healthy_providers(label.llm_type)
        if healthy_providers:
            # 按 Priority 策略选择 (优先级最低的优先)
            selected_name = self._select_by_priority(healthy_providers)
            pool = self._pool_manager.get_pool(selected_name)
            if pool:
                log.debug(
                    "route_type_match",
                    label=str(label),
                    pool=pool.name,
                    candidates=healthy_providers,
                )
                return pool

        log.warning(
            "route_no_match",
            label=str(label),
            llm_type=label.llm_type.value,
        )
        return None

    def route_with_fallback(
        self,
        label: Label,
        fallback_labels: list[Label] | None = None,
    ) -> list[ProviderPool]:
        """路由并返回主备链路。

        Args:
            label: 主标签
            fallback_labels: 备用标签列表

        Returns:
            供应商池列表 (主 + 备用)
        """
        pools: list[ProviderPool] = []

        # 主供应商
        primary_pool = self.route(label)
        if primary_pool:
            pools.append(primary_pool)

        # 备用供应商
        if fallback_labels:
            for fb_label in fallback_labels:
                fb_pool = self.route(fb_label)
                if fb_pool and fb_pool not in pools:
                    pools.append(fb_pool)

        return pools

    def route_for_call_point(
        self,
        call_point: str,
        llm_type: LLMType,
    ) -> list[ProviderPool]:
        """根据调用点配置路由。

        Args:
            call_point: 调用点名称
            llm_type: LLM 类型

        Returns:
            供应商池列表
        """
        config = self._call_point_configs.get(call_point)

        if not config:
            # 没有配置, 使用默认路由
            pool = self.route(Label(llm_type=llm_type, provider="", model=""))
            return [pool] if pool else []

        # 解析主标签
        primary_label_str = config.get("primary", "")
        if isinstance(primary_label_str, str):
            try:
                primary_label = Label.parse(primary_label_str)
            except Exception:
                # 标签解析失败, 尝试使用默认路由
                pool = self._pool_manager.get_pool(primary_label_str)
                return [pool] if pool else []
        else:
            return []

        # 解析备用标签
        fallback_labels: list[Label] = []
        fallbacks = config.get("fallbacks", [])
        if isinstance(fallbacks, list):
            for fb_str in fallbacks:
                if isinstance(fb_str, str):
                    try:
                        fallback_labels.append(Label.parse(fb_str))
                    except Exception:
                        # 忽略无效的备用标签
                        continue

        return self.route_with_fallback(primary_label, fallback_labels)

    def _select_by_priority(self, candidates: list[str]) -> str:
        """按优先级选择供应商。

        Args:
            candidates: 候选供应商名称列表

        Returns:
            选中的供应商名称
        """
        # 获取所有候选者的优先级
        scored: list[tuple[str, int]] = []
        for name in candidates:
            pool = self._pool_manager.get_pool(name)
            if pool:
                scored.append((name, pool.config.priority))

        if not scored:
            return candidates[0] if candidates else ""

        # 按优先级排序 (优先级值越低越优先)
        scored.sort(key=lambda x: x[1])
        return scored[0][0]

    def list_routes(self) -> dict[str, dict[str, str | list[str]]]:
        """列出所有已配置的路由。"""
        return self._call_point_configs.copy()
