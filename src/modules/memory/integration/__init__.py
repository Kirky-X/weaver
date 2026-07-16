# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
