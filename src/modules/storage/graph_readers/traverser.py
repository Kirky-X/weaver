# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Traverser reader for graph repository.

Handles multi-hop graph traversal from a starting entity, with optional
relation-type filtering, path return, and aggregate mode. Result
processing is split into full and aggregate processors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.storage.graph_readers.base import GraphReaderBase

if TYPE_CHECKING:
    pass


class GraphTraverser(GraphReaderBase):
    """Reader for multi-hop graph traversal operations.

    Provides variable-length path traversal from a starting entity with
    optional filtering and aggregation. Query execution with fallback is
    delegated to the injected ``execute_fn`` callable.

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        execute_fn: Callable that runs a query with fallback support.
    """

    async def traverse(
        self,
        start_entity: str,
        max_depth: int = 3,
        relation_types: list[str] | None = None,
        max_results: int = 100,
        timeout_seconds: int = 10,
        return_paths: bool = False,
        mode: str = "full",
        min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        """Multi-hop graph traversal from a starting entity.

        Uses variable-length path matching to discover connected entities
        up to max_depth hops away, with optional filtering and aggregation.

        Args:
            start_entity: Canonical name of the starting entity.
            max_depth: Maximum traversal depth (1-6).
            relation_types: Optional list of relation types to filter.
            max_results: Maximum number of results.
            timeout_seconds: Timeout in seconds.
            return_paths: Whether to return complete paths.
            mode: Traversal mode - 'full' or 'aggregate'.
            min_confidence: Minimum confidence score filter.

        Returns:
            List of result dicts containing nodes, edges, and optionally paths/aggregate.
        """
        # Build and execute the traversal query
        result = await self._execute_fn(
            lambda qb: qb.build_traverse_query(
                max_depth=max_depth,
                relation_types=relation_types,
                return_paths=return_paths,
                mode=mode,
                min_confidence=min_confidence,
            ),
            {
                "center": start_entity,
                "limit": max_results,
            },
        )

        if not result:
            return []

        # Process results based on mode
        if mode == "aggregate":
            return self._process_traverse_aggregate(result)

        return self._process_traverse_full(result, return_paths)

    def _process_traverse_full(
        self, result: list[dict[str, Any]], return_paths: bool
    ) -> list[dict[str, Any]]:
        """Process full traversal results into structured output.

        Args:
            result: Raw query results.
            return_paths: Whether to include path information.

        Returns:
            List of result dicts with nodes, edges, and optionally paths.
        """
        nodes_seen: dict[str, dict[str, Any]] = {}
        edges_seen: set[tuple[str, str, str]] = set()
        paths: list[dict[str, Any]] = []

        for row in result:
            # Collect nodes
            node_name = row.get("node_name", "")
            if node_name and node_name not in nodes_seen:
                nodes_seen[node_name] = {
                    "id": row.get("node_id", ""),
                    "canonical_name": node_name,
                    "type": row.get("node_type", ""),
                    "description": row.get("node_description"),
                }

            # Collect edges
            source = row.get("source", "")
            target = row.get("target", "")
            rel_type = row.get("relation_type", "")
            if source and target and rel_type:
                edge_key = (source, target, rel_type)
                if edge_key not in edges_seen:
                    edges_seen.add(edge_key)

            # Collect path data
            if return_paths and row.get("path_nodes"):
                paths.append(
                    {
                        "nodes": row.get("path_nodes", []),
                        "edges": row.get("path_edges", []),
                    }
                )

        return [
            {
                "nodes": list(nodes_seen.values()),
                "edges": [
                    {"source": s, "target": t, "relation_type": r, "weight": 1.0}
                    for s, t, r in edges_seen
                ],
                "paths": paths if return_paths else None,
            }
        ]

    def _process_traverse_aggregate(self, result: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Process aggregate traversal results.

        Args:
            result: Raw query results.

        Returns:
            List with single result dict containing aggregate statistics.
        """
        total_nodes = 0
        total_edges = 0
        relation_type_counts: dict[str, int] = {}

        for row in result:
            total_nodes = max(total_nodes, row.get("total_nodes", 0))
            total_edges = max(total_edges, row.get("total_edges", 0))
            rt = row.get("relation_type", "")
            count = row.get("type_count", 0)
            if rt:
                relation_type_counts[rt] = count

        return [
            {
                "nodes": [],
                "edges": [],
                "aggregate": {
                    "total_nodes": total_nodes,
                    "total_edges": total_edges,
                    "relation_type_counts": relation_type_counts,
                },
            }
        ]
