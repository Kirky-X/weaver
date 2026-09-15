# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for shared community graph utilities."""

from modules.knowledge.graph.community import graph_utils
from modules.knowledge.graph.community.graph_utils import (
    assign_components_to_uuids,
    build_adjacency,
    find_connected_components_dfs,
)


class TestAssignComponentsToUuids:
    """Test UUID assignment for connected components."""

    def test_uuid_available_at_module_level(self) -> None:
        """#15: ``uuid`` must be a module-level import, not a lazy local one."""
        assert hasattr(graph_utils, "uuid")

    def test_same_component_shares_uuid(self) -> None:
        """Nodes in one component get one shared UUID."""
        assignments = assign_components_to_uuids([{"A", "B"}, {"C"}])

        assert assignments["A"] == assignments["B"]
        assert assignments["C"] != assignments["A"]

    def test_empty_components_produce_no_assignments(self) -> None:
        """No components yields an empty mapping."""
        assert assign_components_to_uuids([]) == {}


class TestBuildAdjacency:
    """Test adjacency construction."""

    def test_undirected_neighbors(self) -> None:
        """Edges are recorded in both directions."""
        adjacency, all_nodes = build_adjacency([("A", "B", 1.0)])

        assert adjacency["A"] == {"B"}
        assert adjacency["B"] == {"A"}
        assert all_nodes == {"A", "B"}

    def test_node_filter_excludes_outside_nodes(self) -> None:
        """Edges touching filtered-out nodes are dropped."""
        adjacency, all_nodes = build_adjacency([("A", "B", 1.0)], node_filter={"A"})

        assert adjacency == {}
        assert all_nodes == set()


class TestFindConnectedComponentsDfs:
    """Test iterative DFS component detection."""

    def test_two_components_found(self) -> None:
        """Disconnected subgraphs yield separate components."""
        adjacency, all_nodes = build_adjacency(
            [("A", "B", 1.0), ("C", "D", 1.0)],
        )

        components = find_connected_components_dfs(adjacency, all_nodes)

        assert {frozenset(c) for c in components} == {frozenset({"A", "B"}), frozenset({"C", "D"})}
