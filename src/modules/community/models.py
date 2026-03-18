# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Community detection data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Community:
    """Represents a community/cluster in the knowledge graph.

    A community is a group of entities that are densely connected
    to each other but sparsely connected to entities in other communities.
    """

    id: str
    level: int
    name: str | None = None
    title: str | None = None
    summary: str | None = None
    entity_ids: list[str] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    parent_community_id: str | None = None
    child_community_ids: list[str] = field(default_factory=list)
    rank: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def size(self) -> int:
        """Number of entities in this community."""
        return len(self.entity_ids)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "level": self.level,
            "name": self.name,
            "title": self.title,
            "summary": self.summary,
            "entity_ids": self.entity_ids,
            "entity_names": self.entity_names,
            "relationship_ids": self.relationship_ids,
            "parent_community_id": self.parent_community_id,
            "child_community_ids": self.child_community_ids,
            "rank": self.rank,
            "size": self.size,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class CommunityHierarchy:
    """Hierarchical structure of communities.

    Supports multi-level community detection where communities
    at higher levels contain communities from lower levels.
    """

    levels: dict[int, list[Community]] = field(default_factory=dict)
    max_level: int = 0

    def add_community(self, community: Community) -> None:
        """Add a community to the hierarchy."""
        if community.level not in self.levels:
            self.levels[community.level] = []
        self.levels[community.level].append(community)
        self.max_level = max(self.max_level, community.level)

    def get_communities_at_level(self, level: int) -> list[Community]:
        """Get all communities at a specific level."""
        return self.levels.get(level, [])

    def get_community_by_id(self, community_id: str) -> Community | None:
        """Find a community by its ID."""
        for communities in self.levels.values():
            for community in communities:
                if community.id == community_id:
                    return community
        return None

    def get_children(self, community_id: str) -> list[Community]:
        """Get child communities of a given community."""
        community = self.get_community_by_id(community_id)
        if not community:
            return []
        return [
            self.get_community_by_id(cid)
            for cid in community.child_community_ids
            if self.get_community_by_id(cid)
        ]

    def get_parent(self, community_id: str) -> Community | None:
        """Get parent community of a given community."""
        community = self.get_community_by_id(community_id)
        if not community or not community.parent_community_id:
            return None
        return self.get_community_by_id(community.parent_community_id)

    def get_leaf_communities(self) -> list[Community]:
        """Get all leaf communities (no children)."""
        leaves = []
        for communities in self.levels.values():
            for community in communities:
                if not community.child_community_ids:
                    leaves.append(community)
        return leaves

    def get_root_communities(self) -> list[Community]:
        """Get all root communities (no parent)."""
        roots = []
        for communities in self.levels.values():
            for community in communities:
                if community.parent_community_id is None:
                    roots.append(community)
        return roots

    def total_communities(self) -> int:
        """Get total number of communities across all levels."""
        return sum(len(communities) for communities in self.levels.values())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "levels": {
                level: [c.to_dict() for c in communities]
                for level, communities in self.levels.items()
            },
            "max_level": self.max_level,
            "total_communities": self.total_communities(),
        }


@dataclass
class ClusteringResult:
    """Result of community clustering operation."""

    partitions: dict[str, int]
    communities: list[Community]
    hierarchy: CommunityHierarchy | None = None
    modularity: float | None = None
    resolution: float = 1.0
    total_entities: int = 0
    total_edges: int = 0

    def get_community_entities(self, community_id: int) -> list[str]:
        """Get entity names for a specific community ID."""
        return [entity for entity, cid in self.partitions.items() if cid == community_id]

    def community_sizes(self) -> dict[int, int]:
        """Get size of each community."""
        sizes: dict[int, int] = {}
        for cid in self.partitions.values():
            sizes[cid] = sizes.get(cid, 0) + 1
        return sizes

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "partitions": self.partitions,
            "communities": [c.to_dict() for c in self.communities],
            "hierarchy": self.hierarchy.to_dict() if self.hierarchy else None,
            "modularity": self.modularity,
            "resolution": self.resolution,
            "total_entities": self.total_entities,
            "total_edges": self.total_edges,
            "community_sizes": self.community_sizes(),
        }
