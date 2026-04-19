# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Causal reasoning module for MAGMA memory system.

Provides:
- CausalInferenceService: LLM-based causal edge inference from entity relations
"""

from modules.memory.causal.causal_inference import (
    CausalInference,
    CausalInferenceService,
    InferenceConfig,
    RelationCategory,
)

__all__ = [
    "CausalInference",
    "CausalInferenceService",
    "InferenceConfig",
    "RelationCategory",
]
