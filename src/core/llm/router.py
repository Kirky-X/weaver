# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Label router for LLM call routing with fallback support."""

from __future__ import annotations

from core.llm.types import GlobalConfig, Label, LLMType, RoutingConfig
from core.observability.logging import get_logger

log = get_logger("label_router")


class LabelRouter:
    """Label路由器.

    处理label解析和fallback链管理.
    """

    def __init__(self, config: GlobalConfig) -> None:
        """初始化路由器.

        Args:
            config: 全局配置
        """
        self._defaults = config.defaults
        self._call_points = config.call_points

    def resolve(self, label: Label) -> list[Label]:
        """解析label，返回包含fallback的标签链.

        Args:
            label: 主label

        Returns:
            标签链 [primary, fallback1, fallback2, ...]
        """
        # 首先查找是否有针对该provider/model的fallback配置
        routing = self._find_routing(label)
        if routing:
            return self._build_chain(routing)

        # 否则只返回主label
        return [label]

    def get_call_point_route(self, call_point: str) -> list[Label]:
        """获取调用点的路由链.

        Args:
            call_point: 调用点名称

        Returns:
            标签链

        Raises:
            ValueError: 调用点未配置
        """
        routing = self._call_points.get(call_point)
        if not routing:
            raise ValueError(f"Call point not configured: {call_point}")

        return self._build_chain(routing)

    def get_default(self, llm_type: LLMType) -> Label:
        """获取指定类型的默认label.

        Args:
            llm_type: LLM类型

        Returns:
            默认label

        Raises:
            ValueError: 未配置默认label
        """
        routing = self._defaults.get(llm_type)
        if not routing:
            raise ValueError(f"No default label configured for {llm_type.value}")

        return Label.parse(routing.primary)

    def _find_routing(self, label: Label) -> RoutingConfig | None:
        """查找label对应的路由配置."""
        # 先查找defaults
        for llm_type, routing in self._defaults.items():
            if routing.primary == str(label):
                return routing

        # 再查找call_points
        for routing in self._call_points.values():
            if routing.primary == str(label):
                return routing

        return None

    def _build_chain(self, routing: RoutingConfig) -> list[Label]:
        """构建label链."""
        chain = [Label.parse(routing.primary)]
        for fb in routing.fallbacks:
            chain.append(Label.parse(fb))
        return chain

    def list_call_points(self) -> list[str]:
        """列出所有配置的调用点."""
        return list(self._call_points.keys())
