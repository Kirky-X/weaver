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
    CacheUsage,
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
    "CacheUsage",
    "CallPoint",
    "CandidateScore",
    "Capability",
    "CircuitState",
    "EvalConfig",
    "EvalRunner",  # Lazy imported via __getattr__
    "ExperienceData",
    "ExperienceStore",  # Lazy imported via __getattr__
    "GlobalConfig",
    "LLMClient",
    "LLMResponse",
    "LLMTask",
    "LLMType",
    "Label",
    "LiveConfig",  # Lazy imported via __getattr__
    "ModelConfig",
    "ModelSelector",  # Lazy imported via __getattr__
    "ProviderConfig",
    "RoutingConfig",
    "RoutingInfeasibleError",
    "RoutingMode",
    "SmartRouter",  # Lazy imported via __getattr__
    "TokenUsage",
]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import for heavy modules to avoid circular dependencies and improve startup time.

    The following modules are lazy-loaded because:
    - They have heavy dependencies (e.g., model loading, network connections)
    - They are not needed in all code paths
    - Deferring import avoids circular dependency issues

    Lazy-loaded symbols:
    - ExperienceStore: Requires experience data loading
    - EvalRunner: Requires evaluation framework setup
    - ModelSelector: Requires model registry initialization
    - SmartRouter: Requires routing configuration
    - LiveConfig: Requires live configuration system
    """
    if name == "ExperienceStore":
        from core.llm.evaluation.experience import ExperienceStore

        return ExperienceStore
    if name == "EvalRunner":
        from core.llm.evaluation.eval_runner import EvalRunner

        return EvalRunner
    if name == "ModelSelector":
        from core.llm.routing.model_selector import ModelSelector

        return ModelSelector
    if name == "SmartRouter":
        from core.llm.routing.smart_router import SmartRouter

        return SmartRouter
    if name == "LiveConfig":
        from core.llm.config.live_config import LiveConfig

        return LiveConfig
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
