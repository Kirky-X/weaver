# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core type definitions shared across modules."""

from core.types.pipeline_state import (
    CredibilityInfo,
    PipelineState,
    get_degradation_summary,
    has_degraded_data,
)

__all__ = [
    "CredibilityInfo",
    "PipelineState",
    "get_degradation_summary",
    "has_degraded_data",
]
