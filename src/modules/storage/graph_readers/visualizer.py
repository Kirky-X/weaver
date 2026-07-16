# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Visualizer reader for graph repository.

Handles graph visualization read operations: top-degree node retrieval,
edge extraction for visualization, and subgraph extraction around a
center entity with hop-pattern and type filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.storage.graph_readers.base import GraphReaderBase

if TYPE_CHECKING:
    pass


class GraphVisualizer(GraphReaderBase):
    """Reader for graph visualization operations.

    Provides nodes and edges for full-graph visualization as well as
    subgraph extraction around a center entity. Query execution with
    fallback is delegated to the injected ``execute_fn`` callable.

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        execute_fn: Callable that runs a query with fallback support.
    """

    async def get_visualization_nodes(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get nodes for graph visualization.

        Args:
            limit: Maximum number of nodes to return.

        Returns:
            List of node dicts with id, label, type, description, and degree.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_visualization_nodes_query(),
            {"limit": limit},
        )
        nodes = []
        for row in result:
            nodes.append(
                {
                    "id": row.get("id") or "",
                    "label": row.get("label") or "",
                    "type": row.get("type") or "未知",
                    "description": row.get("description"),
                    "degree": row.get("degree", 0),
                }
            )
        return nodes

    async def get_visualization_edges(
        self, node_ids: list[str], edge_limit: int = 300
    ) -> list[dict[str, Any]]:
        """Get edges for graph visualization.

        Args:
            node_ids: List of node canonical names to filter edges.
            edge_limit: Maximum number of edges to return.

        Returns:
            List of edge dicts with source, target, relation_type, and weight.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_visualization_edges_query(),
            {"node_ids": node_ids, "edge_limit": edge_limit},
        )
        edges = []
        for row in result:
            edges.append(
                {
                    "source": row.get("source") or "",
                    "target": row.get("target") or "",
                    "relation_type": row.get("relation_type") or "RELATED_TO",
                    "weight": row.get("weight"),
                }
            )
        return edges

    async def get_subgraph_nodes(
        self,
        center_entity: str,
        hop_pattern: str,
        include_types: list[str] | None = None,
        exclude_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get nodes for subgraph extraction around a center entity.

        Args:
            center_entity: Center entity canonical name.
            hop_pattern: Hop pattern like '*1..1', '*1..2', etc.
            include_types: Optional list of entity types to include.
            exclude_types: Optional list of entity types to exclude (applied in Python).

        Returns:
            List of node dicts with id, label, type, and description.
        """
        params: dict[str, Any] = {"center": center_entity}
        if include_types:
            params["include_types"] = include_types
        result = await self._execute_fn(
            lambda qb: qb.build_subgraph_nodes_query(hop_pattern, include_types is not None),
            params,
        )
        nodes = []
        for row in result:
            entity_type = row.get("type") or "未知"
            if exclude_types and entity_type in exclude_types:
                continue
            nodes.append(
                {
                    "id": row.get("id") or "",
                    "label": row.get("label") or "",
                    "type": entity_type,
                    "description": row.get("description"),
                }
            )
        return nodes

    async def get_subgraph_edges(self, node_ids: list[str]) -> list[dict[str, Any]]:
        """Get edges for subgraph visualization.

        Args:
            node_ids: List of node canonical names to filter edges.

        Returns:
            List of edge dicts with source, target, relation_type, and weight.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_subgraph_edges_query(),
            {"node_ids": node_ids},
        )
        edges = []
        for row in result:
            edges.append(
                {
                    "source": row.get("source") or "",
                    "target": row.get("target") or "",
                    "relation_type": row.get("relation_type") or "RELATED_TO",
                    "weight": row.get("weight"),
                }
            )
        return edges
