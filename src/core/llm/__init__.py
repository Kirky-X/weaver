# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LLM module - Unified LLM client with LiteLLM backend.

This module provides a unified interface for LLM interactions with:
- Two-layer nested configuration (Provider + Model)
- LiteLLM unified calling interface
- Label-based routing with fallback support
- Circuit breaker for fault tolerance
- Smart routing with multi-dimensional scoring
- Shadow evaluation for model comparison
- json_repair for robust JSON parsing

Usage:
    from config.settings import Settings
    from core.llm import LLMClient

    settings = Settings()
    client = await LLMClient.create_from_settings(settings.llm)

    # Chat call with label
    response = await client.call("chat.aiping.GLM-4-9B-0414", payload)

    # Using call point routing
    result = await client.call_at("classifier", payload)

    # Embedding
    vectors = await client.embed_default(["text1", "text2"])

    # Rerank
    ranked = await client.rerank_default(query, documents)
"""

from core.llm.client import LLMClient
from core.llm.types import (
    CallPoint,
    CandidateScore,
    Capability,
    CircuitState,
    EvalConfig,
    ExperienceData,
    GlobalConfig,
    Label,
    LLMResponse,
    LLMTask,
    LLMType,
    ModelConfig,
    ProviderConfig,
    RoutingConfig,
    RoutingInfeasibleError,
    RoutingMode,
    TokenUsage,
)

__all__ = [
    "CallPoint",
    "CandidateScore",
    "Capability",
    "CircuitState",
    "EvalConfig",
    "EvalRunner",
    "ExperienceData",
    "ExperienceStore",
    "GlobalConfig",
    "LLMClient",
    "LLMResponse",
    "LLMTask",
    "LLMType",
    "Label",
    "LiveConfig",
    "ModelConfig",
    "ModelSelector",
    "ProviderConfig",
    "RoutingConfig",
    "RoutingInfeasibleError",
    "RoutingMode",
    "SmartRouter",
    "TokenUsage",
]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import for new module-level exports."""
    if name == "ExperienceStore":
        from core.llm.experience import ExperienceStore

        return ExperienceStore
    if name == "EvalRunner":
        from core.llm.eval_runner import EvalRunner

        return EvalRunner
    if name == "ModelSelector":
        from core.llm.model_selector import ModelSelector

        return ModelSelector
    if name == "SmartRouter":
        from core.llm.smart_router import SmartRouter

        return SmartRouter
    if name == "LiveConfig":
        from core.llm.live_config import LiveConfig

        return LiveConfig
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
