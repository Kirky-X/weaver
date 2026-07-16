# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared graph utility functions for community detection.

Provides common graph algorithms used across community detection modules:
- Connected components via DFS
- Adjacency list construction
"""

from __future__ import annotations

from collections import defaultdict


def build_adjacency(
    edges: list[tuple[str, str, float]],
    node_filter: set[str] | None = None,
) -> tuple[dict[str, set[str]], set[str]]:
    """Build adjacency list from edges.

    Args:
        edges: List of (source, target, weight) tuples.
        node_filter: Optional set of nodes to include (None = include all).

    Returns:
        Tuple of (adjacency dict, all_nodes set).
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    all_nodes: set[str] = set()

    for source, target, _ in edges:
        if node_filter is not None:
            if source not in node_filter or target not in node_filter:
                continue
        adjacency[source].add(target)
        adjacency[target].add(source)
        all_nodes.add(source)
        all_nodes.add(target)

    return dict(adjacency), all_nodes


def find_connected_components_dfs(
    adjacency: dict[str, set[str]],
    nodes: set[str],
) -> list[set[str]]:
    """Find connected components using iterative DFS.

    Args:
        adjacency: Adjacency list mapping node to neighbors.
        nodes: Set of all nodes to include in the search.

    Returns:
        List of component sets (each component is a set of node names).
    """
    visited: set[str] = set()
    components: list[set[str]] = []

    for node in nodes:
        if node in visited:
            continue

        # Start a new component via iterative DFS
        component: set[str] = set()
        stack = [node]

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)

            for neighbor in adjacency.get(current, []):
                if neighbor not in visited and neighbor in nodes:
                    stack.append(neighbor)

        if component:
            components.append(component)

    return components


def assign_components_to_uuids(
    components: list[set[str]],
) -> dict[str, str]:
    """Assign a UUID to each connected component.

    Args:
        components: List of component sets.

    Returns:
        Mapping from node name to community UUID.
    """
    import uuid

    assignments: dict[str, str] = {}
    for component in components:
        community_id = str(uuid.uuid4())
        for node in component:
            assignments[node] = community_id
    return assignments
