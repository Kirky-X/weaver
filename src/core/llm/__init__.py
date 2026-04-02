# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""LLM module - Unified LLM client with LiteLLM backend.

This module provides a unified interface for LLM interactions with:
- Two-layer nested configuration (Provider + Model)
- LiteLLM unified calling interface
- Label-based routing with fallback support
- Circuit breaker for fault tolerance
- json_repair for robust JSON parsing

Usage:
    from core.llm import LLMClient

    client = await LLMClient.create_from_config("config/llm.toml")

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
from core.llm.config import LLMConfigLoader
from core.llm.types import (
    CallPoint,
    Capability,
    CircuitState,
    GlobalConfig,
    Label,
    LLMResponse,
    LLMTask,
    LLMType,
    ModelConfig,
    ProviderConfig,
    RoutingConfig,
    TokenUsage,
)

__all__ = [
    "CallPoint",
    "Capability",
    "CircuitState",
    "GlobalConfig",
    "LLMClient",
    "LLMConfigLoader",
    "LLMResponse",
    "LLMTask",
    "LLMType",
    "Label",
    "ModelConfig",
    "ProviderConfig",
    "RoutingConfig",
    "TokenUsage",
]
