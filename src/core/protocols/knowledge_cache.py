# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge cache protocol for cluster caching service.

This module defines the Protocol for knowledge cluster caching,
enabling semantic similarity search and hotness-based eviction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class KnowledgeCluster:
    """Simplified knowledge cluster for caching.

    Stores query results with embeddings for semantic similarity matching.
    Used by AdaptiveSearchEngine for Phase 0 cache lookup.
    """

    id: str
    name: str
    description: str
    content: str
    embedding: list[float] | None = None
    query: str = ""
    hotness: float = 0.5
    create_time: datetime | None = None
    last_modified: datetime | None = None
    version: int = 0

    def __post_init__(self) -> None:
        if self.create_time is None:
            self.create_time = datetime.now()
        if self.last_modified is None:
            self.last_modified = datetime.now()


@runtime_checkable
class KnowledgeCacheProtocol(Protocol):
    """Protocol for knowledge cluster caching service.

    Implementations provide DuckDB in-memory storage with Parquet persistence.
    Used by AdaptiveSearchEngine for Phase 0 cache check.

    Implements:
        KnowledgeCacheProtocol

    Usage:
        cache = container.knowledge_cache()
        similar = await cache.find_similar_cluster(query, threshold=0.85)
        if similar:
            return similar.content  # Cache hit
    """

    async def find_similar_cluster(
        self,
        query: str,
        threshold: float = 0.85,
    ) -> KnowledgeCluster | None:
        """Find similar cached cluster by query embedding similarity.

        Args:
            query: The search query.
            threshold: Minimum cosine similarity threshold (default: 0.85).

        Returns:
            KnowledgeCluster if found, None otherwise.
        """
        ...

    async def store_cluster(self, cluster: KnowledgeCluster) -> str:
        """Store a new cluster or update existing one.

        Computes embedding if not provided.

        Args:
            cluster: The cluster to store.

        Returns:
            The cluster ID.
        """
        ...

    async def get(self, cluster_id: str) -> KnowledgeCluster | None:
        """Get cluster by ID.

        Args:
            cluster_id: The cluster ID.

        Returns:
            KnowledgeCluster if found, None otherwise.
        """
        ...

    async def remove(self, cluster_id: str) -> bool:
        """Remove cluster by ID.

        Args:
            cluster_id: The cluster ID.

        Returns:
            True if removed, False if not found.
        """
        ...

    async def cleanup_stale(self, hotness_threshold: float = 0.3) -> int:
        """Remove clusters below hotness threshold.

        Args:
            hotness_threshold: Minimum hotness to keep (default: 0.3).

        Returns:
            Number of clusters removed.
        """
        ...

    async def update_hotness(self, cluster_id: str, delta: float = 0.1) -> None:
        """Update cluster hotness on reuse.

        Args:
            cluster_id: The cluster ID.
            delta: Hotness increment (default: 0.1).
        """
        ...


__all__ = [
    "KnowledgeCacheProtocol",
    "KnowledgeCluster",
]
