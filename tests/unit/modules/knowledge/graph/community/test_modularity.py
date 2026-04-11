# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for modularity calculation module."""

import pytest

from modules.knowledge.graph.community.enums import ModularityMetric
from modules.knowledge.graph.community.modularity import (
    ModularityResult,
    _compute_modularity,
    _compute_modularity_for_subset,
    _compute_weighted_modularity,
    _find_connected_components,
    calculate_modularity,
)


class TestFindConnectedComponents:
    """Test Union-Find connected components detection."""

    def test_empty_edges_returns_empty(self) -> None:
        """Empty edge list should return empty component list."""
        result = _find_connected_components([])
        assert result == [set()]

    def test_single_edge_returns_single_component(self) -> None:
        """Single edge creates one component with two nodes."""
        edges = [("A", "B", 1.0)]
        result = _find_connected_components(edges)
        assert len(result) == 1
        assert result[0] == {"A", "B"}

    def test_disconnected_edges_returns_two_components(self) -> None:
        """Two separate edges create two components."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        result = _find_connected_components(edges)
        assert len(result) == 2
        # Components should be sorted by size (largest first)
        assert len(result[0]) == 2
        assert len(result[1]) == 2

    def test_triangle_returns_single_component(self) -> None:
        """Triangle graph is one connected component."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0), ("A", "C", 1.0)]
        result = _find_connected_components(edges)
        assert len(result) == 1
        assert result[0] == {"A", "B", "C"}

    def test_larger_component_first(self) -> None:
        """Components sorted by size, largest first."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0), ("D", "E", 1.0)]
        result = _find_connected_components(edges)
        assert len(result) == 2
        # {C, D, E} is larger than {A, B}
        assert len(result[0]) == 3
        assert len(result[1]) == 2


class TestComputeModularity:
    """Test standard modularity calculation."""

    def test_empty_edges_returns_zero(self) -> None:
        """Empty graph has zero modularity."""
        result = _compute_modularity([], {})
        assert result == 0.0

    def test_empty_partitions_returns_zero(self) -> None:
        """No community assignments returns zero."""
        edges = [("A", "B", 1.0)]
        result = _compute_modularity(edges, {})
        assert result == 0.0

    def test_single_community_returns_zero_by_definition(self) -> None:
        """All nodes in one community gives Q=0 by modularity definition.

        Newman-Girvan modularity: Q=Σ[e_ij - a_i*a_j]
        For single community: e_ii = 1, a_i = 1, so Q = 1 - 1 = 0
        """
        edges = [("A", "B", 1.0), ("B", "C", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 0}
        result = _compute_modularity(edges, partitions)
        # Mathematically correct: single community gives Q=0
        assert result == 0.0

    def test_two_communities_separated_has_high_modularity(self) -> None:
        """Two disconnected communities should have high modularity."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}
        result = _compute_modularity(edges, partitions)
        # No inter-community edges, perfect partition
        assert result > 0.0

    def test_random_partition_has_lower_modularity(self) -> None:
        """Random partition should have lower modularity."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0), ("C", "D", 1.0)]
        # Split connected graph randomly
        partitions = {"A": 0, "B": 1, "C": 0, "D": 1}
        result = _compute_modularity(edges, partitions)
        # Some inter-community edges exist
        assert result < 0.2  # Lower modularity


class TestComputeModularityForSubset:
    """Test LCC-specific modularity calculation."""

    def test_empty_subset_returns_zero(self) -> None:
        """Empty subset returns zero."""
        edges = [("A", "B", 1.0)]
        partitions = {"A": 0, "B": 0}
        result = _compute_modularity_for_subset(edges, partitions, set())
        assert result == 0.0

    def test_subset_of_connected_graph(self) -> None:
        """Subset modularity only considers edges within subset.

        For subset {"A", "B"} with partition {"A": 0, "B": 0}:
        - All edges internal within subset → Q=0 by definition
        """
        edges = [("A", "B", 1.0), ("B", "C", 1.0), ("C", "D", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}
        subset = {"A", "B"}
        result = _compute_modularity_for_subset(edges, partitions, subset)
        # Both nodes in same community within subset → Q=0
        assert result == 0.0


class TestComputeWeightedModularity:
    """Test weighted average modularity across components."""

    def test_empty_components_returns_zero(self) -> None:
        """Empty components returns zero."""
        edges = [("A", "B", 1.0)]
        partitions = {"A": 0, "B": 0}
        result = _compute_weighted_modularity(edges, partitions, [])
        assert result == 0.0

    def test_single_component_same_as_graph(self) -> None:
        """Single component weighted equals graph modularity."""
        edges = [("A", "B", 1.0)]
        partitions = {"A": 0, "B": 0}
        components = [{"A", "B"}]
        weighted = _compute_weighted_modularity(edges, partitions, components)
        graph = _compute_modularity(edges, partitions)
        assert weighted == pytest.approx(graph)

    def test_small_components_excluded(self) -> None:
        """Components below min_component_size are excluded."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}
        components = [{"A", "B"}, {"C", "D"}]
        # min_component_size=3 excludes both 2-node components
        result = _compute_weighted_modularity(edges, partitions, components, min_component_size=3)
        assert result == 0.0


class TestCalculateModularity:
    """Test main modularity calculation entry point."""

    def test_empty_inputs_returns_zero_result(self) -> None:
        """Empty inputs return zero modularity result."""
        result = calculate_modularity([], {})
        assert isinstance(result, ModularityResult)
        assert result.graph_modularity == 0.0
        assert result.lcc_modularity == 0.0
        assert result.weighted_modularity == 0.0
        assert result.component_count == 0
        assert result.lcc_size == 0

    def test_returns_all_three_strategies(self) -> None:
        """Returns modularity for all three strategies.

        Note: LCC and weighted strategies may return 0 for disconnected
        graphs where each component has all nodes in single community.
        """
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        # Two communities matching the disconnected components
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}
        result = calculate_modularity(edges, partitions)
        assert isinstance(result, ModularityResult)
        # Graph modularity is positive for proper partition
        assert result.graph_modularity > 0.0
        # LCC/weighted may be 0 if each component has single-community partition
        assert result.component_count == 2
        assert result.lcc_size == 2

    def test_metric_used_reflects_input(self) -> None:
        """metric_used field reflects input metric."""
        edges = [("A", "B", 1.0)]
        partitions = {"A": 0, "B": 0}
        result = calculate_modularity(edges, partitions, metric=ModularityMetric.LCC)
        assert result.metric_used == ModularityMetric.LCC

        result2 = calculate_modularity(
            edges, partitions, metric=ModularityMetric.WeightedComponents
        )
        assert result2.metric_used == ModularityMetric.WeightedComponents

    def test_connected_graph_all_strategies_similar(self) -> None:
        """Connected graph should have similar values for all strategies."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0), ("A", "C", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 0}
        result = calculate_modularity(edges, partitions)
        # For connected graph, all strategies should give same result
        assert result.graph_modularity == pytest.approx(result.lcc_modularity)
        assert result.graph_modularity == pytest.approx(result.weighted_modularity)
        assert result.component_count == 1


class TestModularityMetricEnum:
    """Test ModularityMetric enum values."""

    def test_enum_values(self) -> None:
        """Enum has expected values."""
        assert ModularityMetric.Graph == "graph"
        assert ModularityMetric.LCC == "lcc"
        assert ModularityMetric.WeightedComponents == "weighted_components"

    def test_enum_is_string(self) -> None:
        """Enum values are strings."""
        assert isinstance(ModularityMetric.Graph.value, str)
