# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
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
