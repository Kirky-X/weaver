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

# Knowledge cache protocols
from core.protocols.knowledge_cache import (
    KnowledgeCacheProtocol,
    KnowledgeCluster,
)

# Mapper protocols
from core.protocols.mappers import MapperProtocol

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
    SourceAuthorityRepository,
    VectorRepository,
)

# Service protocols
from core.protocols.services import (
    DeduplicationStrategy,
    EmbeddingServiceProtocol,
    PipelineService,
    TaskRegistryService,
)

# Shared type definitions used in Protocol signatures
from core.protocols.types import (
    PersistStatus,
    PipelineState,
)

# Validation utilities
from core.protocols.validation import (
    assert_implements,
    get_protocol_methods,
)

__all__ = [
    "ArticleRepository",
    "CachePool",
    "DeduplicationStrategy",
    "EmbeddingServiceProtocol",
    "EntityRepository",
    "GraphArticleRepository",
    "GraphPool",
    "GraphWriter",
    "KnowledgeCacheProtocol",
    "KnowledgeCluster",
    "MapperProtocol",
    "PersistStatus",
    "PipelineService",
    "PipelineState",
    "RelationalPool",
    "SourceAuthorityRepository",
    "TaskRegistryService",
    "VectorRepository",
    "assert_implements",
    "get_protocol_methods",
]
