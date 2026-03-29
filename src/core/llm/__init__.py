# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core LLM module - Label-based LLM client and provider management.

This module provides a unified interface for LLM operations with:
- Label-based provider selection (e.g., "chat.aiping.GLM-4-9B-0414")
- Automatic fallback chains
- Provider-level rate limiting and circuit breaking

Example usage:
    from core.llm import LLMClient, Label

    # Create client
    client = await LLMClient.create_from_config(
        "config/llm.toml",
        prompt_loader,
        redis_client,
    )

    # Make a call
    response = await client.call(
        "chat.cc_stitch.claude-sonnet-4",
        payload={"user_content": "Hello"},
    )

"""

from core.llm.label import InvalidLabelError, Label
from core.llm.pool_manager import AllProvidersFailedError, ProviderPoolManager
from core.llm.registry import ProviderInstanceConfig, ProviderRegistry
from core.llm.request import (
    EmbeddingRequest,
    EmbeddingResponse,
    LLMCallResult,
    LLMRequest,
    LLMResponse,
    ProviderMetrics,
    RerankRequest,
    RerankResponse,
    TokenUsage,
)
from core.llm.router import LabelRouter, RoutingStrategy
from core.llm.types import CallPoint, LLMTask, LLMType

__all__ = [
    "AllProvidersFailedError",
    # Core types
    "CallPoint",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "InvalidLabelError",
    # Request/Response
    "LLMCallResult",
    "LLMRequest",
    "LLMResponse",
    "LLMTask",
    "LLMType",
    "Label",
    # Routing
    "LabelRouter",
    "ProviderInstanceConfig",
    "ProviderMetrics",
    # Pool management
    "ProviderPoolManager",
    # Registry
    "ProviderRegistry",
    "RerankRequest",
    "RerankResponse",
    "RoutingStrategy",
    "TokenUsage",
]
