# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline module - Re-exports from processing.pipeline for backward compatibility.

.. deprecated:: 0.3.0
    Import from modules.processing.pipeline instead:

    from modules.processing.pipeline.graph import Pipeline
"""

from core.constants import PipelineState as PipelineStage, ProcessingStatus as PersistStatus

# Re-export other components (these remain local)
from modules.pipeline.config import (
    BatchConfig,
    PhaseConfig,
    PipelineConfig,
    PipelineConfigLoader,
    StageConfig,
    dict_to_config,
    save_default_config,
)
from modules.pipeline.state import PipelineState
from modules.pipeline.state_models import (
    CleanedData,
    CredibilityModel,
    EntityData,
    RelationData,
    ValidatedPipelineState,
    VectorData,
)

# Re-export Pipeline for backward compatibility
from modules.processing.pipeline.graph import Pipeline

__all__ = [
    "BatchConfig",
    "CleanedData",
    "CredibilityModel",
    "EntityData",
    "PersistStatus",
    "PhaseConfig",
    "Pipeline",
    "PipelineConfig",
    "PipelineConfigLoader",
    "PipelineStage",
    "PipelineState",
    "RelationData",
    "StageConfig",
    "ValidatedPipelineState",
    "VectorData",
    "dict_to_config",
    "save_default_config",
]
