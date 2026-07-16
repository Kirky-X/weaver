# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Schemas for graph traverse operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TraverseRequest(BaseModel):
    """Request model for graph traversal.

    Attributes:
        start_entity: Canonical name of the starting entity.
        max_depth: Maximum traversal depth (1-6).
        relation_types: Optional list of relation types to filter.
        max_results: Maximum number of results (1-1000).
        timeout_seconds: Timeout in seconds (1-10).
        return_paths: Whether to return complete paths.
        mode: Traversal mode - 'full' or 'aggregate'.
        min_confidence: Minimum confidence score filter (0.0-1.0).

    """

    start_entity: str = Field(
        ..., min_length=1, description="Canonical name of the starting entity"
    )
    max_depth: int = Field(3, ge=1, le=6, description="Maximum traversal depth (1-6)")
    relation_types: list[str] | None = Field(
        None, description="Optional list of relation types to filter"
    )
    max_results: int = Field(100, ge=1, le=1000, description="Maximum number of results (1-1000)")
    timeout_seconds: int = Field(10, ge=1, le=10, description="Timeout in seconds (1-10)")
    return_paths: bool = Field(False, description="Whether to return complete paths")
    mode: str = Field("full", pattern="^(full|aggregate)$", description="Traversal mode")
    min_confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Minimum confidence score filter (0.0-1.0)"
    )


class PathNode(BaseModel):
    """Node in a traversal path.

    Attributes:
        id: Node identifier.
        canonical_name: Entity canonical name.
        type: Entity type.
        description: Optional entity description.

    """

    id: str
    canonical_name: str
    type: str
    description: str | None = None


class EdgeResponse(BaseModel):
    """Edge in a traversal result.

    Attributes:
        source: Source entity canonical name.
        target: Target entity canonical name.
        relation_type: Type of the relationship.
        weight: Relationship weight.

    """

    source: str
    target: str
    relation_type: str
    weight: float | None = None


class PathResponse(BaseModel):
    """A complete path in the traversal.

    Attributes:
        nodes: List of node names in the path.
        edges: List of edges in the path.

    """

    nodes: list[str]
    edges: list[dict[str, Any]]


class TraverseResultItem(BaseModel):
    """A single result item from traversal.

    Attributes:
        nodes: Discovered nodes.
        edges: Discovered edges.
        paths: Complete paths (when return_paths=True).
        aggregate: Aggregate statistics (when mode='aggregate').

    """

    nodes: list[PathNode] = Field(default_factory=list)
    edges: list[EdgeResponse] = Field(default_factory=list)
    paths: list[PathResponse] | None = None
    aggregate: dict[str, Any] | None = None


class TraverseStatistics(BaseModel):
    """Statistics for a graph traversal operation.

    Attributes:
        nodes_visited: Total number of nodes visited during traversal.
        edges_traversed: Total number of edges traversed during traversal.
        depth_reached: Maximum depth reached during traversal.
        execution_time_ms: Execution time in milliseconds, if measured.

    """

    nodes_visited: int = 0
    edges_traversed: int = 0
    depth_reached: int = 0
    execution_time_ms: int | None = None


class TraverseResponse(BaseModel):
    """Response model for graph traversal.

    Attributes:
        results: List of traversal result items.
        statistics: Traversal statistics (nodes visited, edges traversed, depth reached).

    """

    results: list[TraverseResultItem] = Field(default_factory=list)
    statistics: TraverseStatistics = Field(default_factory=TraverseStatistics)
