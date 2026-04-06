# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Central protocol definitions for dependency injection.

This module re-exports all Protocol classes from their respective modules
for convenient importing.

Import from this module:
    from core.protocols import RelationalPool, GraphPool, CachePool
    from core.protocols import EntityRepository, VectorRepository, ArticleRepository

Protocol categories:
    - Pool protocols: Database and cache connection pool interfaces
    - Repository protocols: Data access layer interfaces
    - Validation utilities: Runtime protocol verification
"""

from __future__ import annotations

# Pool protocols
from core.protocols.pools import (
    CachePool,
    GraphPool,
    RelationalPool,
)

# Repository protocols
from core.protocols.repositories import (
    ArticleRepository,
    EntityRepository,
    GraphArticleRepository,
    GraphWriter,
    PendingSyncRepository,
    SourceAuthorityRepository,
    VectorRepository,
)

# Service protocols
from core.protocols.services import (
    PipelineService,
    TaskRegistryService,
)

# Validation utilities
from core.protocols.validation import (
    assert_implements,
    get_protocol_methods,
)

__all__ = [
    "ArticleRepository",
    "CachePool",
    "EntityRepository",
    "GraphArticleRepository",
    "GraphPool",
    "GraphWriter",
    "PendingSyncRepository",
    "PipelineService",
    "RelationalPool",
    "SourceAuthorityRepository",
    "TaskRegistryService",
    "VectorRepository",
    "assert_implements",
    "get_protocol_methods",
]
