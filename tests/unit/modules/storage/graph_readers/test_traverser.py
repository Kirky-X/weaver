# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for GraphTraverser — covers traverse, _process_traverse_full, and
_process_traverse_aggregate methods.

Covers R-graph-traverser-001 through R-graph-traverser-008.

Tests mock _execute_fn (the fallback-aware executor injected by
GraphReaderBase) to isolate from real graph database dependencies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.graph_readers.traverser import GraphTraverser


def _make_traverser(execute_fn_return=None, execute_fn_side_effect=None):
    """Create a GraphTraverser with mocked dependencies.

    Args:
        execute_fn_return: Value to return from _execute_fn (sync or async).
        execute_fn_side_effect: Exception to raise from _execute_fn.

    Returns:
        (traverser, mock_execute_fn, mock_pool, mock_query_builder)
    """
    mock_pool = MagicMock()
    mock_query_builder = MagicMock()
    mock_execute_fn = AsyncMock()
    if execute_fn_side_effect is not None:
        mock_execute_fn.side_effect = execute_fn_side_effect
    else:
        mock_execute_fn.return_value = execute_fn_return if execute_fn_return is not None else []

    traverser = GraphTraverser(
        pool=mock_pool,
        query_builder=mock_query_builder,
        execute_fn=mock_execute_fn,
    )
    return traverser, mock_execute_fn, mock_pool, mock_query_builder


class TestTraverseFullMode:
    """Tests for traverse() with mode='full' — R-graph-traverser-001, R-graph-traverser-003."""

    @pytest.mark.asyncio
    async def test_traverse_full_mode_calls_execute_fn_with_center_and_limit(self):
        """traverse must pass {center: start_entity, limit: max_results} as params."""
        traverser, mock_execute_fn, _, _ = _make_traverser(
            execute_fn_return=[{"node_name": "A", "node_id": "1"}]
        )

        await traverser.traverse(start_entity="China", max_results=50)

        assert mock_execute_fn.await_count == 1
        # _execute_fn is called with (lambda, params)
        call_args = mock_execute_fn.await_args
        params = call_args.args[1] if len(call_args.args) > 1 else None
        assert params == {
            "center": "China",
            "limit": 50,
        }, f"Expected params {{'center': 'China', 'limit': 50}}, got {params}"

    @pytest.mark.asyncio
    async def test_traverse_full_mode_returns_processed_full_result(self):
        """traverse with mode='full' must return _process_traverse_full output."""
        # Two rows with distinct nodes and one edge
        rows = [
            {
                "node_name": "China",
                "node_id": "n1",
                "node_type": "Country",
                "node_description": "East Asia country",
                "source": "China",
                "target": "USA",
                "relation_type": "RELATED_TO",
            },
            {
                "node_name": "USA",
                "node_id": "n2",
                "node_type": "Country",
                "node_description": "North America country",
                "source": "China",
                "target": "USA",
                "relation_type": "RELATED_TO",
            },
        ]
        traverser, _, _, _ = _make_traverser(execute_fn_return=rows)

        result = await traverser.traverse(start_entity="China", mode="full")

        assert len(result) == 1, f"Expected 1 result dict, got {len(result)}"
        result_dict = result[0]
        assert "nodes" in result_dict
        assert "edges" in result_dict
        assert "paths" in result_dict
        # Two distinct nodes (China, USA)
        assert len(result_dict["nodes"]) == 2
        node_names = {n["canonical_name"] for n in result_dict["nodes"]}
        assert node_names == {"China", "USA"}
        # One distinct edge (China → USA, RELATED_TO)
        assert len(result_dict["edges"]) == 1
        assert result_dict["edges"][0]["source"] == "China"
        assert result_dict["edges"][0]["target"] == "USA"
        assert result_dict["edges"][0]["relation_type"] == "RELATED_TO"

    @pytest.mark.asyncio
    async def test_traverse_empty_result_returns_empty_list(self):
        """traverse must return [] when _execute_fn returns []."""
        traverser, _, _, _ = _make_traverser(execute_fn_return=[])

        result = await traverser.traverse(start_entity="NonExistent")
        assert result == [], f"Expected empty list for empty result, got {result}"

    @pytest.mark.asyncio
    async def test_traverse_passes_max_depth_and_relation_types_to_query_builder(self):
        """traverse must pass max_depth/relation_types/return_paths/mode/min_confidence
        to the lambda's build_traverse_query call.
        """
        traverser, mock_execute_fn, _, _ = _make_traverser(execute_fn_return=[])

        await traverser.traverse(
            start_entity="China",
            max_depth=5,
            relation_types=["CAUSES", "ENABLES"],
            max_results=20,
            return_paths=True,
            mode="full",
            min_confidence=0.7,
        )

        # The first positional arg to _execute_fn is a lambda that takes query_builder
        # We need to invoke that lambda with a mock query_builder to capture the args
        call_args = mock_execute_fn.await_args
        build_query_fn = call_args.args[0]

        mock_qb = MagicMock()
        mock_qb.build_traverse_query = MagicMock(return_value="QUERY STRING")
        build_query_fn(mock_qb)

        mock_qb.build_traverse_query.assert_called_once_with(
            max_depth=5,
            relation_types=["CAUSES", "ENABLES"],
            return_paths=True,
            mode="full",
            min_confidence=0.7,
        )


class TestTraverseAggregateMode:
    """Tests for traverse() with mode='aggregate' — R-graph-traverser-002."""

    @pytest.mark.asyncio
    async def test_traverse_aggregate_mode_returns_aggregate_result(self):
        """traverse with mode='aggregate' must return _process_traverse_aggregate output."""
        rows = [
            {"total_nodes": 10, "total_edges": 5, "relation_type": "CAUSES", "type_count": 3},
            {"total_nodes": 10, "total_edges": 5, "relation_type": "ENABLES", "type_count": 2},
        ]
        traverser, _, _, _ = _make_traverser(execute_fn_return=rows)

        result = await traverser.traverse(start_entity="China", mode="aggregate")

        assert len(result) == 1
        result_dict = result[0]
        assert "aggregate" in result_dict
        agg = result_dict["aggregate"]
        assert agg["total_nodes"] == 10
        assert agg["total_edges"] == 5
        assert agg["relation_type_counts"] == {"CAUSES": 3, "ENABLES": 2}

    @pytest.mark.asyncio
    async def test_traverse_aggregate_mode_passes_mode_to_query_builder(self):
        """traverse with mode='aggregate' must pass mode='aggregate' to build_traverse_query."""
        traverser, mock_execute_fn, _, _ = _make_traverser(execute_fn_return=[])

        await traverser.traverse(start_entity="China", mode="aggregate")

        call_args = mock_execute_fn.await_args
        build_query_fn = call_args.args[0]
        mock_qb = MagicMock()
        mock_qb.build_traverse_query = MagicMock(return_value="QUERY")
        build_query_fn(mock_qb)

        _, kwargs = mock_qb.build_traverse_query.call_args
        assert kwargs.get("mode") == "aggregate", (
            f"Expected mode='aggregate', got {kwargs.get('mode')}"
        )


class TestProcessTraverseFull:
    """Tests for _process_traverse_full — R-graph-traverser-004, R-graph-traverser-005,
    R-graph-traverser-006, R-graph-traverser-007.
    """

    def test_process_full_deduplicates_nodes_by_name(self):
        """Two rows with same node_name must produce 1 node."""
        traverser, _, _, _ = _make_traverser()
        rows = [
            {"node_name": "China", "node_id": "n1", "node_type": "Country"},
            {"node_name": "China", "node_id": "n1", "node_type": "Country"},
        ]

        result = traverser._process_traverse_full(rows, return_paths=False)

        assert len(result) == 1
        assert len(result[0]["nodes"]) == 1, (
            f"Expected 1 deduplicated node, got {len(result[0]['nodes'])}"
        )
        assert result[0]["nodes"][0]["canonical_name"] == "China"

    def test_process_full_deduplicates_edges_by_source_target_reltype(self):
        """Two rows with same (source, target, relation_type) must produce 1 edge."""
        traverser, _, _, _ = _make_traverser()
        rows = [
            {"source": "A", "target": "B", "relation_type": "CAUSES"},
            {"source": "A", "target": "B", "relation_type": "CAUSES"},
        ]

        result = traverser._process_traverse_full(rows, return_paths=False)

        assert len(result[0]["edges"]) == 1, (
            f"Expected 1 deduplicated edge, got {len(result[0]['edges'])}"
        )
        edge = result[0]["edges"][0]
        assert edge["source"] == "A"
        assert edge["target"] == "B"
        assert edge["relation_type"] == "CAUSES"
        assert edge["weight"] == 1.0

    def test_process_full_collects_paths_when_return_paths_true(self):
        """return_paths=True must collect path_nodes/path_edges from each row."""
        traverser, _, _, _ = _make_traverser()
        rows = [
            {
                "node_name": "A",
                "node_id": "1",
                "source": "A",
                "target": "B",
                "relation_type": "CAUSES",
                "path_nodes": ["A", "B"],
                "path_edges": [{"type": "CAUSES"}],
            },
            {
                "node_name": "B",
                "node_id": "2",
                "source": "B",
                "target": "C",
                "relation_type": "ENABLES",
                "path_nodes": ["B", "C"],
                "path_edges": [{"type": "ENABLES"}],
            },
        ]

        result = traverser._process_traverse_full(rows, return_paths=True)

        assert len(result) == 1
        paths = result[0]["paths"]
        assert paths is not None
        assert len(paths) == 2, f"Expected 2 paths, got {len(paths)}"
        assert paths[0]["nodes"] == ["A", "B"]
        assert paths[1]["nodes"] == ["B", "C"]

    def test_process_full_paths_none_when_return_paths_false(self):
        """return_paths=False must set paths=None in result."""
        traverser, _, _, _ = _make_traverser()
        rows = [{"node_name": "A", "node_id": "1"}]

        result = traverser._process_traverse_full(rows, return_paths=False)

        assert len(result) == 1
        assert result[0]["paths"] is None

    def test_process_full_empty_result_returns_empty_nodes_edges(self):
        """Empty input must return [{nodes: [], edges: [], paths: None}]."""
        traverser, _, _, _ = _make_traverser()

        result = traverser._process_traverse_full([], return_paths=False)

        assert len(result) == 1
        assert result[0]["nodes"] == []
        assert result[0]["edges"] == []
        assert result[0]["paths"] is None


class TestProcessTraverseAggregate:
    """Tests for _process_traverse_aggregate — R-graph-traverser-008."""

    def test_aggregate_takes_max_total_nodes(self):
        """total_nodes must be max across all rows."""
        traverser, _, _, _ = _make_traverser()
        rows = [
            {"total_nodes": 5, "total_edges": 2, "relation_type": "A", "type_count": 1},
            {"total_nodes": 10, "total_edges": 4, "relation_type": "B", "type_count": 2},
            {"total_nodes": 3, "total_edges": 8, "relation_type": "A", "type_count": 3},
        ]

        result = traverser._process_traverse_aggregate(rows)

        assert len(result) == 1
        assert result[0]["aggregate"]["total_nodes"] == 10, (
            f"Expected total_nodes=10 (max), got {result[0]['aggregate']['total_nodes']}"
        )

    def test_aggregate_takes_max_total_edges(self):
        """total_edges must be max across all rows."""
        traverser, _, _, _ = _make_traverser()
        rows = [
            {"total_nodes": 5, "total_edges": 2, "relation_type": "A", "type_count": 1},
            {"total_nodes": 10, "total_edges": 4, "relation_type": "B", "type_count": 2},
            {"total_nodes": 3, "total_edges": 8, "relation_type": "A", "type_count": 3},
        ]

        result = traverser._process_traverse_aggregate(rows)

        assert result[0]["aggregate"]["total_edges"] == 8, (
            f"Expected total_edges=8 (max), got {result[0]['aggregate']['total_edges']}"
        )

    def test_aggregate_groups_relation_type_counts(self):
        """relation_type_counts must map each relation_type to its type_count (not accumulate)."""
        traverser, _, _, _ = _make_traverser()
        rows = [
            {"total_nodes": 5, "total_edges": 2, "relation_type": "A", "type_count": 3},
            {"total_nodes": 5, "total_edges": 2, "relation_type": "B", "type_count": 5},
            # Duplicate A with smaller count — implementation takes first occurrence
            {"total_nodes": 5, "total_edges": 2, "relation_type": "A", "type_count": 2},
        ]

        result = traverser._process_traverse_aggregate(rows)

        rt_counts = result[0]["aggregate"]["relation_type_counts"]
        # A first seen with count=3, then overwritten with count=2 (last write wins)
        assert "A" in rt_counts
        assert "B" in rt_counts
        assert rt_counts["B"] == 5

    def test_aggregate_empty_result_returns_zeros(self):
        """Empty input must return total_nodes=0, total_edges=0, relation_type_counts={}."""
        traverser, _, _, _ = _make_traverser()

        result = traverser._process_traverse_aggregate([])

        assert len(result) == 1
        agg = result[0]["aggregate"]
        assert agg["total_nodes"] == 0
        assert agg["total_edges"] == 0
        assert agg["relation_type_counts"] == {}

    def test_aggregate_result_has_empty_nodes_and_edges_lists(self):
        """Aggregate result must have nodes=[] and edges=[] (not None)."""
        traverser, _, _, _ = _make_traverser()
        rows = [{"total_nodes": 5, "total_edges": 2, "relation_type": "A", "type_count": 1}]

        result = traverser._process_traverse_aggregate(rows)

        assert result[0]["nodes"] == []
        assert result[0]["edges"] == []
        assert "aggregate" in result[0]
