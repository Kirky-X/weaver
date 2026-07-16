# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
