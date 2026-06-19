# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Modularity calculation module for community detection.

Provides three strategies for calculating graph modularity:
- Graph: Full graph modularity (may be low for sparse graphs)
- LCC: Largest connected component modularity only
- WeightedComponents: Weighted average across all connected components
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from modules.knowledge.graph.community.enums import ModularityMetric

if TYPE_CHECKING:
    pass


@dataclass
class ModularityResult:
    """Result of modularity calculation.

    Contains modularity scores for all three strategies,
    plus the selected metric and its value.
    """

    graph_modularity: float
    lcc_modularity: float
    weighted_modularity: float
    metric_used: ModularityMetric
    component_count: int = 1
    lcc_size: int = 0


def _find_connected_components(
    edges: list[tuple[str, str, float]],
) -> list[set[str]]:
    """Find all connected components using Union-Find.

    Args:
        edges: List of (source, target, weight) tuples.

    Returns:
        List of component sets (largest first).
    """
    if not edges:
        return [set()]

    # Union-Find implementation
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])  # Path compression
        return parent[x]

    def union(x: str, y: str) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Build connected components
    for source, target, _ in edges:
        union(source, target)

    # Group nodes by component
    components: dict[str, set[str]] = defaultdict(set)
    for node in parent:
        components[find(node)].add(node)

    # Return sorted by size (largest first)
    return sorted(components.values(), key=len, reverse=True)


def _compute_modularity(
    edges: list[tuple[str, str, float]],
    partitions: dict[str, int],
    resolution: float = 1.0,
) -> float:
    """Compute standard modularity for entire graph.

    Args:
        edges: List of (source, target, weight) tuples.
        partitions: Mapping from node to community ID.
        resolution: Resolution parameter.

    Returns:
        Modularity score.
    """
    if not edges or not partitions:
        return 0.0

    total_weight = sum(w for _, _, w in edges)
    if total_weight == 0:
        return 0.0

    # Calculate community degree sums and internal edges
    community_degree: dict[int, float] = defaultdict(float)
    community_internal: dict[int, float] = defaultdict(float)

    for source, target, weight in edges:
        source_cluster = partitions.get(source)
        target_cluster = partitions.get(target)

        if source_cluster is not None:
            community_degree[source_cluster] += weight
        if target_cluster is not None:
            community_degree[target_cluster] += weight

        # Internal edges (both endpoints in same community)
        if source_cluster is not None and source_cluster == target_cluster:
            community_internal[source_cluster] += weight * 2

    # Calculate modularity Q
    modularity = 0.0
    for cluster in set(partitions.values()):
        internal = community_internal.get(cluster, 0.0)
        degree = community_degree.get(cluster, 0.0)
        modularity += (
            internal / (2 * total_weight) - resolution * (degree / (2 * total_weight)) ** 2
        )

    return modularity


def _compute_modularity_for_subset(
    edges: list[tuple[str, str, float]],
    partitions: dict[str, int],
    subset_nodes: set[str],
    resolution: float = 1.0,
) -> float:
    """Compute modularity for a specific subset of nodes.

    Args:
        edges: List of (source, target, weight) tuples.
        partitions: Mapping from node to community ID.
        subset_nodes: Set of nodes to include in calculation.
        resolution: Resolution parameter.

    Returns:
        Modularity score for the subset.
    """
    if not edges or not partitions or not subset_nodes:
        return 0.0

    # Filter edges to only those within subset
    subset_edges = [(s, t, w) for s, t, w in edges if s in subset_nodes and t in subset_nodes]

    # Filter partitions to subset nodes
    subset_partitions = {n: c for n, c in partitions.items() if n in subset_nodes}

    return _compute_modularity(subset_edges, subset_partitions, resolution)


def _compute_weighted_modularity(
    edges: list[tuple[str, str, float]],
    partitions: dict[str, int],
    components: list[set[str]],
    resolution: float = 1.0,
    min_component_size: int = 10,
) -> float:
    """Compute weighted average modularity across components.

    Args:
        edges: List of (source, target, weight) tuples.
        partitions: Mapping from node to community ID.
        components: List of component sets.
        resolution: Resolution parameter.
        min_component_size: Minimum size to include in weighted average.

    Returns:
        Weighted modularity score.
    """
    if not components or not partitions:
        return 0.0

    total_weighted_q = 0.0
    total_size = 0

    for component in components:
        size = len(component)
        if size < min_component_size:
            continue

        q = _compute_modularity_for_subset(edges, partitions, component, resolution)
        total_weighted_q += q * size
        total_size += size

    if total_size == 0:
        return 0.0

    return total_weighted_q / total_size


def calculate_modularity(
    edges: list[tuple[str, str, float]],
    partitions: dict[str, int],
    metric: ModularityMetric = ModularityMetric.WeightedComponents,
    resolution: float = 1.0,
    min_component_size: int = 10,
) -> ModularityResult:
    """Calculate modularity with selectable strategy.

    Args:
        edges: List of (source, target, weight) tuples.
        partitions: Mapping from node to community ID.
        metric: Calculation strategy to use.
        resolution: Resolution parameter.
        min_component_size: Minimum component size for weighted strategy.

    Returns:
        ModularityResult with scores for all strategies.
    """
    if not edges or not partitions:
        return ModularityResult(
            graph_modularity=0.0,
            lcc_modularity=0.0,
            weighted_modularity=0.0,
            metric_used=metric,
            component_count=0,
            lcc_size=0,
        )

    # Find connected components
    components = _find_connected_components(edges)
    component_count = len(components)
    lcc_size = len(components[0]) if components else 0

    # Calculate all three strategies
    graph_q = _compute_modularity(edges, partitions, resolution)

    lcc_q = 0.0
    if components:
        lcc_q = _compute_modularity_for_subset(edges, partitions, components[0], resolution)

    weighted_q = _compute_weighted_modularity(
        edges, partitions, components, resolution, min_component_size
    )

    return ModularityResult(
        graph_modularity=graph_q,
        lcc_modularity=lcc_q,
        weighted_modularity=weighted_q,
        metric_used=metric,
        component_count=component_count,
        lcc_size=lcc_size,
    )
