"""Leiden algorithm for community detection.

Implementation based on the Leiden algorithm for community detection,
which improves upon the Louvain algorithm by guaranteeing well-connected communities.

Reference: "From Louvain to Leiden: guaranteeing well-connected communities"
by Traag, Waltman, and van Eck (2019)
"""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.observability.logging import get_logger
from modules.community.models import Community, CommunityHierarchy, ClusteringResult
from modules.community.modularity import ModularityCalculator

log = get_logger("community.leiden")


@dataclass
class GraphPartition:
    """Internal representation of graph partition."""

    nodes: set[str] = field(default_factory=set)
    edges: list[tuple[str, str, float]] = field(default_factory=list)
    adjacency: dict[str, dict[str, float]] = field(default_factory=dict)
    node_to_community: dict[str, int] = field(default_factory=dict)
    community_to_nodes: dict[int, set[str]] = field(default_factory=dict)
    total_weight: float = 0.0

    def add_edge(self, source: str, target: str, weight: float = 1.0) -> None:
        """Add an edge to the graph."""
        self.nodes.add(source)
        self.nodes.add(target)
        self.edges.append((source, target, weight))

        if source not in self.adjacency:
            self.adjacency[source] = {}
        self.adjacency[source][target] = weight

        if target not in self.adjacency:
            self.adjacency[target] = {}
        self.adjacency[target][source] = weight

        self.total_weight += weight

    def initialize_singleton_partition(self) -> None:
        """Initialize each node in its own community."""
        self.node_to_community = {}
        self.community_to_nodes = {}

        for i, node in enumerate(sorted(self.nodes)):
            self.node_to_community[node] = i
            self.community_to_nodes[i] = {node}

    def get_node_degree(self, node: str) -> float:
        """Get the weighted degree of a node."""
        return sum(self.adjacency.get(node, {}).values())

    def get_community_weight(self, community: int) -> float:
        """Get the total weight of edges within a community."""
        nodes = self.community_to_nodes.get(community, set())
        weight = 0.0
        for node in nodes:
            for neighbor, w in self.adjacency.get(node, {}).items():
                if neighbor in nodes:
                    weight += w
        return weight / 2

    def get_edges_between_communities(self, comm1: int, comm2: int) -> float:
        """Get the total weight of edges between two communities."""
        nodes1 = self.community_to_nodes.get(comm1, set())
        nodes2 = self.community_to_nodes.get(comm2, set())
        weight = 0.0
        for node in nodes1:
            for neighbor, w in self.adjacency.get(node, {}).items():
                if neighbor in nodes2:
                    weight += w
        return weight


class LeidenClustering:
    """Leiden algorithm for community detection.

    The Leiden algorithm finds communities by optimizing modularity
    through three phases:
    1. Local moving: Move nodes to neighboring communities
    2. Refinement: Refine the partition to ensure well-connectedness
    3. Aggregation: Aggregate the graph based on the refined partition

    The algorithm is deterministic when using a fixed random seed.
    """

    def __init__(
        self,
        resolution: float = 1.0,
        random_seed: int | None = None,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
    ) -> None:
        """Initialize Leiden clustering.

        Args:
            resolution: Resolution parameter for modularity optimization.
                Higher values lead to smaller communities.
            random_seed: Random seed for reproducibility.
            max_iterations: Maximum number of iterations per level.
            tolerance: Convergence tolerance for modularity improvement.
        """
        self._resolution = resolution
        self._random_seed = random_seed
        self._max_iterations = max_iterations
        self._tolerance = tolerance
        self._modularity_calc = ModularityCalculator(resolution)

        if random_seed is not None:
            random.seed(random_seed)

    def cluster(
        self,
        edges: list[tuple[str, str, float]],
        node_names: dict[str, str] | None = None,
    ) -> ClusteringResult:
        """Perform Leiden clustering on the graph.

        Args:
            edges: List of (source, target, weight) tuples.
            node_names: Optional mapping of node IDs to display names.

        Returns:
            ClusteringResult with partitions and community information.
        """
        if not edges:
            return ClusteringResult(
                partitions={},
                communities=[],
                modularity=0.0,
                resolution=self._resolution,
            )

        partition = self._build_partition(edges)
        partition.initialize_singleton_partition()

        hierarchy = CommunityHierarchy()
        level = 0

        while True:
            improved = self._local_moving_phase(partition)

            if not improved and level > 0:
                break

            self._refinement_phase(partition)

            communities = self._create_communities(partition, node_names or {}, level)
            for comm in communities:
                hierarchy.add_community(comm)

            if len(partition.community_to_nodes) == len(partition.nodes):
                break

            partition = self._aggregate_partition(partition)
            level += 1

            if level >= 10:
                break

        modularity = self._modularity_calc.calculate(
            edges, partition.node_to_community
        )

        all_communities = []
        for communities in hierarchy.levels.values():
            all_communities.extend(communities)

        return ClusteringResult(
            partitions=partition.node_to_community,
            communities=all_communities,
            hierarchy=hierarchy,
            modularity=modularity.score,
            resolution=self._resolution,
            total_entities=len(partition.nodes),
            total_edges=len(edges),
        )

    def _build_partition(self, edges: list[tuple[str, str, float]]) -> GraphPartition:
        """Build initial graph partition from edges."""
        partition = GraphPartition()
        for source, target, weight in edges:
            partition.add_edge(source, target, weight)
        return partition

    def _local_moving_phase(self, partition: GraphPartition) -> bool:
        """Phase 1: Move nodes to optimize modularity.

        Returns:
            True if any improvement was made, False otherwise.
        """
        improved = False
        nodes = list(partition.nodes)
        random.shuffle(nodes)

        for iteration in range(self._max_iterations):
            any_moved = False

            for node in nodes:
                best_community = self._find_best_community(partition, node)
                current_community = partition.node_to_community[node]

                if best_community != current_community:
                    self._move_node(partition, node, best_community)
                    any_moved = True
                    improved = True

            if not any_moved:
                break

        return improved

    def _find_best_community(self, partition: GraphPartition, node: str) -> int:
        """Find the best community for a node based on modularity gain."""
        current_community = partition.node_to_community[node]
        neighbor_communities = set()

        for neighbor in partition.adjacency.get(node, {}):
            neighbor_communities.add(partition.node_to_community[neighbor])

        neighbor_communities.add(current_community)

        best_community = current_community
        best_gain = 0.0

        node_degree = partition.get_node_degree(node)

        for community in neighbor_communities:
            gain = self._calculate_modularity_gain(
                partition, node, community, node_degree
            )
            if gain > best_gain:
                best_gain = gain
                best_community = community

        return best_community

    def _calculate_modularity_gain(
        self,
        partition: GraphPartition,
        node: str,
        target_community: int,
        node_degree: float,
    ) -> float:
        """Calculate modularity gain for moving node to target community."""
        edges_to_community = 0.0
        for neighbor, weight in partition.adjacency.get(node, {}).items():
            if partition.node_to_community.get(neighbor) == target_community:
                edges_to_community += weight

        community_weight = partition.get_community_weight(target_community)
        total_weight = partition.total_weight

        gain = edges_to_community - self._resolution * (
            node_degree * community_weight / total_weight
        )

        return gain

    def _move_node(
        self,
        partition: GraphPartition,
        node: str,
        new_community: int,
    ) -> None:
        """Move a node to a new community."""
        old_community = partition.node_to_community[node]

        partition.community_to_nodes[old_community].discard(node)
        if not partition.community_to_nodes[old_community]:
            del partition.community_to_nodes[old_community]

        if new_community not in partition.community_to_nodes:
            partition.community_to_nodes[new_community] = set()
        partition.community_to_nodes[new_community].add(node)

        partition.node_to_community[node] = new_community

    def _refinement_phase(self, partition: GraphPartition) -> None:
        """Phase 2: Refine partition to ensure well-connected communities."""
        refined_partition = GraphPartition()
        refined_partition.nodes = partition.nodes.copy()
        refined_partition.adjacency = partition.adjacency.copy()
        refined_partition.edges = partition.edges.copy()
        refined_partition.total_weight = partition.total_weight
        refined_partition.node_to_community = partition.node_to_community.copy()
        refined_partition.community_to_nodes = {
            k: v.copy() for k, v in partition.community_to_nodes.items()
        }

        for community_id, nodes in list(partition.community_to_nodes.items()):
            if len(nodes) <= 1:
                continue

            subgraph_nodes = set(nodes)
            sub_communities = self._find_sub_communities(
                refined_partition, subgraph_nodes, community_id
            )

            if sub_communities:
                for i, sub_nodes in enumerate(sub_communities):
                    new_community_id = max(partition.community_to_nodes.keys()) + 1 + i
                    for node in sub_nodes:
                        partition.node_to_community[node] = new_community_id
                        partition.community_to_nodes[community_id].discard(node)
                    partition.community_to_nodes[new_community_id] = sub_nodes

    def _find_sub_communities(
        self,
        partition: GraphPartition,
        nodes: set[str],
        original_community: int,
    ) -> list[set[str]]:
        """Find well-connected sub-communities within a community."""
        if len(nodes) <= 2:
            return []

        visited = set()
        sub_communities = []

        for start_node in nodes:
            if start_node in visited:
                continue

            component = self._bfs_component(partition, start_node, nodes)
            visited.update(component)

            if len(component) < len(nodes) and len(component) >= 1:
                sub_communities.append(component)

        return sub_communities

    def _bfs_component(
        self,
        partition: GraphPartition,
        start: str,
        nodes: set[str],
    ) -> set[str]:
        """Find connected component using BFS."""
        component = set()
        queue = [start]
        visited = set()

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)

            if node in nodes:
                component.add(node)
                for neighbor in partition.adjacency.get(node, {}):
                    if neighbor in nodes and neighbor not in visited:
                        queue.append(neighbor)

        return component

    def _aggregate_partition(self, partition: GraphPartition) -> GraphPartition:
        """Phase 3: Aggregate graph based on current partition."""
        new_partition = GraphPartition()

        community_weights: dict[tuple[int, int], float] = defaultdict(float)

        for source, target, weight in partition.edges:
            source_comm = partition.node_to_community[source]
            target_comm = partition.node_to_community[target]
            community_weights[(source_comm, target_comm)] += weight

        for (comm1, comm2), weight in community_weights.items():
            comm1_str = f"comm_{comm1}"
            comm2_str = f"comm_{comm2}"
            new_partition.add_edge(comm1_str, comm2_str, weight)

        new_partition.initialize_singleton_partition()

        old_to_new = {}
        for node, old_comm in partition.node_to_community.items():
            new_comm_str = f"comm_{old_comm}"
            old_to_new[node] = new_partition.node_to_community[new_comm_str]

        return new_partition

    def _create_communities(
        self,
        partition: GraphPartition,
        node_names: dict[str, str],
        level: int,
    ) -> list[Community]:
        """Create Community objects from partition."""
        communities = []

        for community_id, nodes in partition.community_to_nodes.items():
            entity_names = [
                node_names.get(node, node)
                for node in nodes
            ]

            community = Community(
                id=str(uuid.uuid4()),
                level=level,
                name=f"Community_{community_id}",
                entity_ids=list(nodes),
                entity_names=entity_names,
            )
            communities.append(community)

        return communities

    def cluster_with_hierarchy(
        self,
        edges: list[tuple[str, str, float]],
        node_names: dict[str, str] | None = None,
    ) -> ClusteringResult:
        """Perform hierarchical Leiden clustering.

        This method runs the Leiden algorithm and builds a complete
        hierarchy of communities from leaf to root.

        Args:
            edges: List of (source, target, weight) tuples.
            node_names: Optional mapping of node IDs to display names.

        Returns:
            ClusteringResult with full hierarchy information.
        """
        result = self.cluster(edges, node_names)

        if result.hierarchy:
            self._build_hierarchy_relationships(result.hierarchy)

        return result

    def _build_hierarchy_relationships(
        self,
        hierarchy: CommunityHierarchy,
    ) -> None:
        """Build parent-child relationships in hierarchy."""
        for level in range(hierarchy.max_level):
            current_level_communities = hierarchy.get_communities_at_level(level)
            next_level_communities = hierarchy.get_communities_at_level(level + 1)

            for child in next_level_communities:
                for parent in current_level_communities:
                    if set(child.entity_ids).issubset(set(parent.entity_ids)):
                        child.parent_community_id = parent.id
                        if child.id not in parent.child_community_ids:
                            parent.child_community_ids.append(child.id)
                        break
