# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM module type definitions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, field_validator


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
    COMMUNITY_TITLE = "community_title"
    CAUSAL_INFERENCE = "causal_inference"
    ENTITY_FACTS = "entity_facts"
    NARRATIVE_SYNTHESIS = "narrative_synthesis"
    EVIDENCE_SAMPLING = "evidence_sampling"
    ROI_SUMMARY = "roi_summary"
    SENTIMENT = "sentiment"
    CLAIM_EXTRACTION = "claim_extraction"


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
    """LLM调用标签,用于标识调用类型、供应商和模型.

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
            label: 标签字符串,格式为 'type.provider.model'

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
    cached_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True, slots=True)
class CacheUsage:
    """服务端 prompt cache 使用情况归一化表示.

    用于统一表示 DeepSeek 顶层字段（prompt_cache_hit_tokens / prompt_cache_miss_tokens）
    与 OpenAI 嵌套字段（prompt_tokens_details.cached_tokens）的缓存命中信息。

    Attributes:
        cache_hit_tokens: 命中服务端缓存的 token 数.
        cache_miss_tokens: 未命中服务端缓存的 token 数.
        reasoning_tokens: 推理 token 数（来自 completion_tokens_details.reasoning_tokens）.
    """

    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率 = hit / (hit + miss).

        总数为零时返回 0.0（除零保护）.
        """
        total = self.cache_hit_tokens + self.cache_miss_tokens
        if total == 0:
            return 0.0
        return self.cache_hit_tokens / total


def _parse_cache_usage(raw_usage: dict[str, Any]) -> CacheUsage:
    """解析 provider 响应中的 cache 字段为归一化 CacheUsage.

    作为服务端缓存字段解析的**唯一入口**，优先读取 DeepSeek 顶层字段
    `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`；当两者缺失或全为 0 时，
    回退读取 OpenAI/MiMo 嵌套字段 `prompt_tokens_details.cached_tokens`，
    并从 `prompt_tokens - hit` 推导 `miss`。

    Args:
        raw_usage: LiteLLM 响应的 usage 字典（已转为 dict）。

    Returns:
        归一化的 CacheUsage；无任何 cache 字段时返回全 0（优雅降级，不抛异常）。
    """
    if not raw_usage:
        return CacheUsage()

    # 1. DeepSeek 顶层字段(优先)
    deepseek_hit = raw_usage.get("prompt_cache_hit_tokens") or 0
    deepseek_miss = raw_usage.get("prompt_cache_miss_tokens") or 0

    if deepseek_hit > 0 or deepseek_miss > 0:
        hit = deepseek_hit
        miss = deepseek_miss
    else:
        # 2. OpenAI/MiMo 嵌套字段回退
        details = raw_usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens") or 0 if isinstance(details, dict) else 0
        if cached > 0:
            hit = cached
            prompt_tokens = raw_usage.get("prompt_tokens") or 0
            miss = max(prompt_tokens - hit, 0)
        else:
            hit = 0
            miss = 0

    # 3. reasoning_tokens(独立于 hit/miss 逻辑)
    comp_details = raw_usage.get("completion_tokens_details") or {}
    reasoning = comp_details.get("reasoning_tokens") or 0 if isinstance(comp_details, dict) else 0

    return CacheUsage(
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        reasoning_tokens=reasoning,
    )


@dataclass
class LLMResponse:
    """LLM调用响应."""

    content: Any  # str | list[list[float]] | list[dict]
    label: Label
    latency_ms: float
    token_usage: TokenUsage | None
    model: str
    # 服务端 prompt cache 字段(由 _parse_cache_usage 填充; provider 无 cache 字段时为 0)
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0


class TierConfig(BaseModel):
    """Tiered routing tier configuration - pydantic BaseModel for TOML loading."""

    label: str = ""
    max_difficulty: float = 1.0
    input_truncation: int | None = None


class RoutingConfig(BaseModel):
    """路由配置 - pydantic BaseModel for TOML loading."""

    primary: str = ""
    fallbacks: list[str] = []
    think: bool | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    response_format: str | None = None  # "json" for Ollama JSON mode

    # Tiered routing (difficulty-based provider selection)
    tiered_routing: bool = False
    tiers: list[TierConfig] = []

    def __post_init__(self) -> None:
        """Ensure fallbacks is initialized."""
        if self.fallbacks is None:
            self.fallbacks = []


class ModelConfig(BaseModel):
    """模型配置(第二层)- pydantic BaseModel for TOML loading."""

    model_id: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None
    think: bool | None = None
    capabilities: frozenset[Capability] = frozenset()

    @field_validator("capabilities", mode="before")
    @classmethod
    def parse_capabilities(cls, v: Any) -> frozenset[Capability]:
        """Parse capabilities from list of strings."""
        if isinstance(v, frozenset):
            return v
        if isinstance(v, list):
            return frozenset(Capability(c.strip()) for c in v if c.strip())
        return frozenset()

    def supports(self, llm_type: LLMType) -> bool:
        """检查是否支持指定的LLM类型."""
        type_to_cap = {
            LLMType.CHAT: Capability.CHAT,
            LLMType.EMBEDDING: Capability.EMBEDDING,
            LLMType.RERANK: Capability.RERANK,
        }
        return type_to_cap.get(llm_type) in self.capabilities


class ProviderConfig(BaseModel):
    """Provider厂商配置(第一层)- pydantic BaseModel for TOML loading."""

    name: str = ""
    type: str = "openai"  # LiteLLM provider type
    api_key: str = ""
    base_url: str = ""
    rpm_limit: int = 60
    concurrency: int = 5
    timeout: float = 120.0
    priority: int = 100
    weight: int = 100
    models: dict[str, ModelConfig] = {}
    # 请求延迟配置(可选,覆盖全局配置)
    request_delay_enabled: bool | None = None
    request_delay_min: float | None = None
    request_delay_max: float | None = None

    def get_model(self, model_name: str) -> ModelConfig | None:
        """获取模型配置."""
        return self.models.get(model_name)


class GlobalConfig(BaseModel):
    """全局配置 - pydantic BaseModel for TOML loading."""

    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0
    default_timeout: float = 120.0
    # 请求延迟配置
    request_delay_enabled: bool = False
    request_delay_min: float = 1.0
    request_delay_max: float = 2.0
    defaults: dict[str, RoutingConfig] = {}
    call_points: dict[str, RoutingConfig] = {}

    @field_validator("defaults", "call_points", mode="before")
    @classmethod
    def parse_routing_dict(cls, v: Any) -> dict[str, RoutingConfig]:
        """Parse routing config dict."""
        if v is None:
            return {}
        if isinstance(v, dict):
            result: dict[str, RoutingConfig] = {}
            for key, val in v.items():
                if isinstance(val, RoutingConfig):
                    result[key] = val
                elif isinstance(val, dict):
                    result[key] = RoutingConfig(**val)
            return result
        return {}


class RoutingMode(str, Enum):
    """Routing mode controlling the balance between cost and quality."""

    AUTO = "auto"
    FAST = "fast"
    BEST = "best"

    @classmethod
    def from_str(cls, value: str) -> RoutingMode:
        """Convert string to RoutingMode enum.

        Args:
            value: String value to convert.

        Returns:
            Corresponding RoutingMode enum member.

        Raises:
            ValueError: If value is not a valid routing mode.
        """
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [m.value for m in cls]
            raise ValueError(f"Invalid routing mode '{value}'. Valid values: {valid_values}")


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Scored candidate model for selection.

    Attributes:
        model: Model name (e.g., "GLM-Z1-9B-0414")
        provider: Provider name (e.g., "aiping")
        total: Weighted total score
        editorial_score: Preset priority score [0, 1]
        reliability_score: Historical success rate [0, 1]
        cost_score: Normalized cost score [0, 1]
        latency_score: Normalized latency score [0, 1]
    """

    model: str
    provider: str
    total: float
    editorial_score: float
    reliability_score: float
    cost_score: float
    latency_score: float


@dataclass(frozen=True, slots=True)
class ExperienceData:
    """Runtime experience data for a (call_point, provider, model) triplet.

    Attributes:
        call_count: Total number of calls
        success_count: Number of successful calls
        failure_count: Number of failed calls
        total_latency_ms: Sum of all latencies
        avg_latency_ms: Average latency
        last_call_time: Timestamp of last call
        thompson_alpha: Beta distribution alpha parameter
        thompson_beta: Beta distribution beta parameter
        last_error_type: Last error type string
    """

    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    last_call_time: float = 0.0
    thompson_alpha: float = 1.0
    thompson_beta: float = 1.0
    last_error_type: str = ""


@dataclass(frozen=True, slots=True)
class EvalConfig:
    """Shadow evaluation configuration.

    Attributes:
        enabled: Whether shadow evaluation is enabled
        sample_rate: Fraction of requests to shadow (0.0 to 1.0)
        target_call_points: List of call points to evaluate
        baseline_model: Baseline model label for comparison
        candidate_models: List of candidate model labels to compare
    """

    enabled: bool = False
    sample_rate: float = 0.1
    target_call_points: list[str] = ()  # type: ignore[assignment]
    baseline_model: str = ""
    candidate_models: list[str] = ()  # type: ignore[assignment]


# Cache TTL per call point (in seconds)
CACHE_TTL: dict[str, int] = {
    "classifier": 7 * 24 * 60 * 60,
    "categorizer": 7 * 24 * 60 * 60,
    "quality_scorer": 24 * 60 * 60,
    "credibility_checker": 24 * 60 * 60,
    "analyze": 24 * 60 * 60,
    "summary": 7 * 24 * 60 * 60,
    "entity_extractor": 7 * 24 * 60 * 60,
    "default": 24 * 60 * 60,
}


class RoutingInfeasibleError(Exception):
    """Raised when no candidate model satisfies the routing constraints.

    Attributes:
        message: Human-readable error message
        reason: Machine-readable reason code
    """

    def __init__(self, message: str, reason: str = "no_available_models") -> None:
        self.message = message
        self.reason = reason
        super().__init__(message)


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
