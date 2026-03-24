# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Data models for community detection and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Community:
    """Represents a community of related entities in the knowledge graph.

    Communities are detected using Hierarchical Leiden algorithm and
    form a hierarchical structure where level 0 contains the most
    fine-grained communities.

    Attributes:
        id: Unique identifier (UUID).
        title: Human-readable title for the community.
        level: Hierarchy level (0 = leaf/most granular, higher = more abstract).
        parent_id: ID of parent community in hierarchy (None for root).
        entity_ids: List of entity IDs belonging to this community.
        entity_count: Number of entities in the community.
        relationship_ids: List of relationship IDs within the community.
        rank: Importance ranking score (higher = more important).
        period: Date when community was detected (YYYY-MM-DD).
        modularity: Modularity contribution of this community.
        created_at: Timestamp when community was created.
        updated_at: Timestamp when community was last updated.
    """

    id: str
    title: str
    level: int
    parent_id: str | None = None
    entity_ids: list[str] = field(default_factory=list)
    entity_count: int = 0
    relationship_ids: list[str] = field(default_factory=list)
    rank: float = 1.0
    period: str | None = None
    modularity: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_neo4j(cls, data: dict[str, Any]) -> Community:
        """Create Community from Neo4j query result.

        Args:
            data: Dictionary from Neo4j query.

        Returns:
            Community instance.
        """
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            level=data.get("level", 0),
            parent_id=data.get("parent_id"),
            entity_ids=data.get("entity_ids", []),
            entity_count=data.get("entity_count", 0),
            relationship_ids=data.get("relationship_ids", []),
            rank=data.get("rank", 1.0),
            period=data.get("period"),
            modularity=data.get("modularity"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class CommunityReport:
    """LLM-generated report for a community.

    Contains structured summary and analysis of a community's
    entities, relationships, and themes.

    Attributes:
        id: Unique identifier (UUID).
        community_id: ID of the community this report describes.
        title: Title of the report.
        summary: Short summary (100-200 characters).
        full_content: Full report content (1000-2000 characters).
        key_entities: List of key entity names identified in the report.
        key_relationships: List of key relationship descriptions.
        rank: Importance ranking (1-10, higher = more important).
        full_content_embedding: Vector embedding of full_content.
        stale: Whether the report needs regeneration.
        created_at: Timestamp when report was generated.
        updated_at: Timestamp when report was last updated.
    """

    id: str
    community_id: str
    title: str
    summary: str = ""
    full_content: str = ""
    key_entities: list[str] = field(default_factory=list)
    key_relationships: list[str] = field(default_factory=list)
    rank: float = 5.0
    full_content_embedding: list[float] | None = None
    stale: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_neo4j(cls, data: dict[str, Any]) -> CommunityReport:
        """Create CommunityReport from Neo4j query result.

        Args:
            data: Dictionary from Neo4j query.

        Returns:
            CommunityReport instance.
        """
        return cls(
            id=data.get("id", ""),
            community_id=data.get("community_id", ""),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            full_content=data.get("full_content", ""),
            key_entities=data.get("key_entities", []),
            key_relationships=data.get("key_relationships", []),
            rank=data.get("rank", 5.0),
            full_content_embedding=data.get("full_content_embedding"),
            stale=data.get("stale", False),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class HierarchicalCluster:
    """Result from Hierarchical Leiden algorithm.

    Represents a single node's assignment to a community at a specific
    level of the hierarchy.

    Attributes:
        node: Entity identifier (canonical_name).
        cluster: Community ID at this level.
        level: Hierarchy level (0 = leaf).
        parent_cluster: Parent community ID (None for root).
        is_final_cluster: Whether this is the final stable cluster.
    """

    node: str
    cluster: int
    level: int
    parent_cluster: int | None = None
    is_final_cluster: bool = False


@dataclass
class CommunityDetectionResult:
    """Result of community detection process.

    Attributes:
        communities: List of detected communities.
        total_entities: Total number of entities processed.
        total_communities: Total number of communities created.
        modularity: Overall graph modularity score.
        levels: Number of hierarchy levels.
        orphan_count: Number of entities with no relationships.
        execution_time_ms: Time taken for detection in milliseconds.
    """

    communities: list[Community]
    total_entities: int = 0
    total_communities: int = 0
    modularity: float = 0.0
    levels: int = 1
    orphan_count: int = 0
    execution_time_ms: float = 0.0
