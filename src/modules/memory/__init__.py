# Copyright (c) 2026 KirkyX. All Rights Reserved
"""MAGMA-style multi-graph memory module.

This module provides:
- core: Core data types (IntentType, OutputMode, EventNode)
- graphs: Graph repositories (TemporalGraphRepo, CausalGraphRepo)
- retrieval: Adaptive search and retrieval
- evolution: Memory consolidation and synaptic ingestion
- integration: Integration with existing pipeline and container

Note: This is an actively developed module. Import from specific submodules:
    from modules.memory.core.graph_types import IntentType, OutputMode
    from modules.memory.graphs.temporal import TemporalGraphRepo
    from modules.memory.integration import MemoryIntegrationService
"""

# Core types commonly used across the application
from modules.memory.core.graph_types import IntentType, OutputMode

# Integration service
from modules.memory.integration import (
    IntentClassifierAdapter,
    MemoryIntegrationService,
    MemoryServiceConfig,
)

__all__ = [
    "IntentClassifierAdapter",
    "IntentType",
    "MemoryIntegrationService",
    "MemoryServiceConfig",
    "OutputMode",
]
