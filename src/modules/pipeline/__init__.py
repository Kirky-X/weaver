# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline module - Data processing pipeline with LangGraph.

This module provides:
- Pipeline: Main processing pipeline (import from graph)
- PipelineState: State management for pipeline execution
- PipelineConfig: Configuration data classes
- PipelineConfigLoader: Configuration file loader

Usage:
    # Direct imports (recommended)
    from modules.pipeline.graph import Pipeline
    from modules.pipeline.config import PipelineConfig, PipelineConfigLoader

    # Configuration-driven initialization
    loader = PipelineConfigLoader()
    config = loader.load_with_env_override()
    pipeline = Pipeline.from_config(llm, config, ...)
"""

# Import from core.constants instead of deprecated state_models aliases
from core.constants import PipelineState as PipelineStage, ProcessingStatus as PersistStatus
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

__all__ = [
    # Config
    "BatchConfig",
    "CleanedData",
    "CredibilityModel",
    "EntityData",
    "PersistStatus",
    "PhaseConfig",
    "PipelineConfig",
    "PipelineConfigLoader",
    "PipelineStage",
    # State (TypedDict - legacy)
    "PipelineState",
    "RelationData",
    "StageConfig",
    # State (Pydantic - validated, recommended for new code)
    "ValidatedPipelineState",
    "VectorData",
    "dict_to_config",
    "save_default_config",
]
