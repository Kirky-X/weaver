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


# Shared mapping from LLMType to Capability (canonical, used across modules)
TYPE_TO_CAPABILITY: dict[LLMType, Capability] = {
    LLMType.CHAT: Capability.CHAT,
    LLMType.EMBEDDING: Capability.EMBEDDING,
    LLMType.RERANK: Capability.RERANK,
}


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


@dataclass(frozen=True)
class CacheUsage:
    """Server-side prompt cache usage (DeepSeek/OpenAI).

    Normalized representation of provider-specific cache fields:
    - DeepSeek: prompt_cache_hit_tokens / prompt_cache_miss_tokens
    - OpenAI: prompt_tokens_details.cached_tokens (mapped to cache_hit_tokens)

    Attributes:
        cache_hit_tokens: Tokens served from server cache.
        cache_miss_tokens: Tokens not served from cache (computed as prompt_tokens - cache_hit_tokens when available).
        reasoning_tokens: Reasoning tokens (from completion_tokens_details.reasoning_tokens).
    """

    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        """Cache hit rate (0.0-1.0). Returns 0.0 on zero-division."""
        total = self.cache_hit_tokens + self.cache_miss_tokens
        if total == 0:
            return 0.0
        return self.cache_hit_tokens / total


@dataclass
class LLMResponse:
    """LLM调用响应."""

    content: Any  # str | list[list[float]] | list[dict]
    label: Label
    latency_ms: float
    token_usage: TokenUsage | None
    model: str
    # 服务端 prompt cache 使用情况(由 caller.py chat() 填充; provider 无 cache 字段时为 None)
    cache_usage: CacheUsage | None = None


class TierConfig(BaseModel):
    """Tiered routing tier configuration - pydantic BaseModel for TOML loading."""

    label: str = ""
    max_difficulty: float = 1.0
    input_truncation: int | None = None


def validate_tiers(tiers: list[TierConfig]) -> list[str]:
    """Validate a list of TierConfig entries for correctness.

    Checks:
    - max_difficulty values are in range [0.0, 1.0]
    - max_difficulty values are strictly ascending
    - No duplicate max_difficulty values
    - Last tier covers max_difficulty=1.0 (warning if not)

    Args:
        tiers: List of TierConfig entries to validate.

    Returns:
        List of error/warning strings. Empty list means valid.
    """
    errors: list[str] = []

    if not tiers:
        return errors

    for i, tier in enumerate(tiers):
        if not (0.0 <= tier.max_difficulty <= 1.0):
            errors.append(
                f"Tier {i} ({tier.label}): max_difficulty={tier.max_difficulty} "
                f"is out of range [0.0, 1.0]"
            )

    for i in range(1, len(tiers)):
        if tiers[i].max_difficulty <= tiers[i - 1].max_difficulty:
            errors.append(
                f"Non-ascending max_difficulty: tier {i - 1} "
                f"({tiers[i - 1].max_difficulty}) >= tier {i} "
                f"({tiers[i].max_difficulty})"
            )

    # Check for duplicates
    difficulties = [t.max_difficulty for t in tiers]
    seen: set[float] = set()
    for d in difficulties:
        if d in seen:
            errors.append(f"Duplicate max_difficulty value: {d}")
        seen.add(d)

    # Check coverage
    if tiers[-1].max_difficulty < 1.0:
        errors.append(
            f"Last tier max_difficulty={tiers[-1].max_difficulty} < 1.0: "
            f"difficulty scores above this value will have no coverage"
        )

    return errors


def describe_routing(tiers: list[TierConfig]) -> str:
    """Generate a human-readable description of the routing table.

    Args:
        tiers: List of TierConfig entries.

    Returns:
        Multi-line string describing the routing decisions.
    """
    if not tiers:
        return "No tiers configured — tiered routing is disabled."

    lines = ["Tiered routing configuration:"]
    prev_bound = 0.0
    for i, tier in enumerate(tiers):
        range_str = f"[{prev_bound:.1f}, {tier.max_difficulty:.1f})"
        truncation = f", truncation={tier.input_truncation}" if tier.input_truncation else ""
        lines.append(f"  Tier {i}: difficulty {range_str} → {tier.label}{truncation}")
        prev_bound = tier.max_difficulty

    # Validate and append warnings
    errors = validate_tiers(tiers)
    if errors:
        lines.append("")
        lines.append("Validation warnings:")
        for error in errors:
            lines.append(f"  ⚠ {error}")

    return "\n".join(lines)


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


def parse_routing_dict_shared(v: Any) -> dict[str, RoutingConfig]:
    """Parse routing config dict (shared validator logic).

    Converts raw dict data into RoutingConfig objects, including tier parsing.
    Used by both GlobalConfig and LLMSettings field validators.

    Args:
        v: Raw value from TOML/config (dict, None, or dict of RoutingConfig).

    Returns:
        Dict mapping call point name to RoutingConfig.
    """
    if v is None:
        return {}
    if isinstance(v, dict):
        result: dict[str, RoutingConfig] = {}
        for key, val in v.items():
            if isinstance(val, RoutingConfig):
                result[key] = val
            elif isinstance(val, dict):
                # Parse tiers if present (enhanced version)
                tiers_data = val.pop("tiers", None)
                tiers: list[TierConfig] = []
                if isinstance(tiers_data, list):
                    for tier_data in tiers_data:
                        if isinstance(tier_data, TierConfig):
                            tiers.append(tier_data)
                        elif isinstance(tier_data, dict):
                            tiers.append(TierConfig(**tier_data))
                val["tiers"] = tiers
                result[key] = RoutingConfig(**val)
        return result
    return {}


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
        return TYPE_TO_CAPABILITY.get(llm_type) in self.capabilities


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
        """Parse routing config dict (delegates to shared function)."""
        return parse_routing_dict_shared(v)


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
    provider_cfg: ProviderConfig | None = field(default=None, init=False)
    future: asyncio.Future | None = field(default=None, init=False)

    def __lt__(self, other: LLMTask) -> bool:
        """Support PriorityQueue ordering."""
        return self.priority < other.priority
