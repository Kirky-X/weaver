# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""LLM module type definitions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LLMType(str, Enum):
    """LLM调用类型."""

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class CallPoint(str, Enum):
    """Pipeline call points that invoke LLM operations."""

    CLASSIFIER = "classifier"
    CLEANER = "cleaner"
    CATEGORIZER = "categorizer"
    MERGER = "merger"
    ANALYZE = "analyze"
    CREDIBILITY_CHECKER = "credibility_checker"
    QUALITY_SCORER = "quality_scorer"
    ENTITY_EXTRACTOR = "entity_extractor"
    ENTITY_RESOLVER = "entity_resolver"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    SEARCH_LOCAL = "search_local"
    SEARCH_GLOBAL = "search_global"
    COMMUNITY_REPORT = "community_report"


class Capability(str, Enum):
    """模型能力标识."""

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VISION = "vision"


class CircuitState(str, Enum):
    """熔断器状态."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class Label:
    """LLM调用标签，用于标识调用类型、供应商和模型.

    格式: {type}.{provider}.{model}
    示例: chat.aiping.GLM-4-9B-0414
    """

    llm_type: LLMType
    provider: str
    model: str

    @classmethod
    def parse(cls, label: str) -> Label:
        """解析标签字符串.

        Args:
            label: 标签字符串，格式为 'type.provider.model'

        Returns:
            解析后的Label对象

        Raises:
            ValueError: 标签格式无效
        """
        parts = label.split(".", 2)
        if len(parts) != 3:
            raise ValueError(
                f"Invalid label format: '{label}'. "
                f"Expected format: 'type.provider.model' "
                f"(e.g., 'chat.aiping.GLM-4-9B-0414')"
            )

        type_str, provider, model = parts

        try:
            llm_type = LLMType(type_str)
        except ValueError:
            raise ValueError(
                f"Invalid LLM type: '{type_str}'. Valid types: {[t.value for t in LLMType]}"
            ) from None

        if not provider or not model:
            raise ValueError(f"Provider and model cannot be empty in label: '{label}'")

        return cls(llm_type=llm_type, provider=provider, model=model)

    def __str__(self) -> str:
        return f"{self.llm_type.value}.{self.provider}.{self.model}"


@dataclass
class TokenUsage:
    """Token使用量."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM调用响应."""

    content: Any  # str | list[list[float]] | list[dict]
    label: Label
    latency_ms: float
    token_usage: TokenUsage | None
    model: str


@dataclass
class RoutingConfig:
    """路由配置."""

    primary: str
    fallbacks: list[str] = None

    def __post_init__(self):
        if self.fallbacks is None:
            self.fallbacks = []


@dataclass
class ModelConfig:
    """模型配置（第二层）."""

    model_id: str
    temperature: float = 0.0
    max_tokens: int | None = None
    capabilities: frozenset[Capability] = frozenset()

    def supports(self, llm_type: LLMType) -> bool:
        """检查是否支持指定的LLM类型."""
        type_to_cap = {
            LLMType.CHAT: Capability.CHAT,
            LLMType.EMBEDDING: Capability.EMBEDDING,
            LLMType.RERANK: Capability.RERANK,
        }
        return type_to_cap.get(llm_type) in self.capabilities


@dataclass
class ProviderConfig:
    """Provider厂商配置（第一层）."""

    name: str
    type: str  # LiteLLM provider type
    api_key: str
    base_url: str
    rpm_limit: int = 60
    concurrency: int = 5
    timeout: float = 120.0
    priority: int = 100
    weight: int = 100
    models: dict[str, ModelConfig] = None

    def __post_init__(self):
        if self.models is None:
            self.models = {}

    def get_model(self, model_name: str) -> ModelConfig | None:
        """获取模型配置."""
        return self.models.get(model_name)


@dataclass
class GlobalConfig:
    """全局配置."""

    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0
    default_timeout: float = 120.0
    defaults: dict[LLMType, RoutingConfig] = None
    call_points: dict[str, RoutingConfig] = None

    def __post_init__(self):
        if self.defaults is None:
            self.defaults = {}
        if self.call_points is None:
            self.call_points = {}


@dataclass
class LLMTask:
    """Represents a single LLM operation to be queued and executed.

    Attributes:
        call_point: The pipeline stage initiating this call.
        llm_type: Type of LLM interaction.
        payload: Input data for the LLM call.
        priority: Priority level (lower = higher priority).
        attempt: Current retry count for self-retry logic.
        provider_cfg: Provider configuration (set by QueueManager).
        future: Asyncio future for result delivery.
    """

    call_point: CallPoint
    llm_type: LLMType
    payload: dict[str, Any]
    priority: int = 5
    attempt: int = 0
    provider_cfg: Any = field(default=None, init=False)
    future: asyncio.Future | None = field(default=None, init=False)

    def __lt__(self, other: LLMTask) -> bool:
        """Support PriorityQueue ordering."""
        return self.priority < other.priority
