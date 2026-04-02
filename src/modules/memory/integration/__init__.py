# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration hooks with existing pipeline and container."""

from modules.memory.integration.memory_service import (
    IntentClassifierAdapter,
    MemoryIntegrationService,
    MemoryServiceConfig,
)

__all__ = [
    "IntentClassifierAdapter",
    "MemoryIntegrationService",
    "MemoryServiceConfig",
]
