# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline state type definitions.

Re-export from core.types.pipeline_state for backward compatibility.
The canonical location is now core/types/pipeline_state.py to break
circular dependencies between storage/processing/ingestion modules.
"""

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
