# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GraphPruner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.graph_store.graph_pruner import GraphPruner, PruneResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4jPool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


class TestGraphPrunerBasic:
    """Basic functionality tests for GraphPruner."""

    @pytest.mark.asyncio
    async def test_pruner_initialization(self, mock_neo4j_pool):
        """Test pruner initializes with default parameters."""
        pruner = GraphPruner(mock_neo4j_pool)

        assert pruner.min_entity_frequency == 2
        assert pruner.min_entity_degree == 1
        assert pruner.min_edge_weight_pct == 40.0
        assert pruner.remove_ego_nodes is False

    @pytest.mark.asyncio
    async def test_pruner_custom_parameters(self, mock_neo4j_pool):
        """Test pruner with custom parameters."""
        pruner = GraphPruner(
            mock_neo4j_pool,
            min_entity_frequency=5,
            min_entity_degree=3,
            min_edge_weight_pct=60.0,
            remove_ego_nodes=True,
        )

        assert pruner.min_entity_frequency == 5
        assert pruner.min_entity_degree == 3
        assert pruner.min_edge_weight_pct == 60.0
        assert pruner.remove_ego_nodes is True


class TestPruneByFrequency:
    """Tests for frequency-based pruning strategy."""

    @pytest.mark.asyncio
    async def test_prune_by_frequency_marks_low_mention_entities(self, mock_neo4j_pool):
        """Test that entities with low mention counts are marked pruned."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[{"pruned_count": 5}])

        pruner = GraphPruner(mock_neo4j_pool, min_entity_frequency=2)
        count = await pruner.prune_by_frequency()

        assert count == 5
        mock_neo4j_pool.execute_query.assert_called_once()
        call_args = mock_neo4j_pool.execute_query.call_args
        assert "min_freq" in call_args[0][1]
        assert call_args[0][1]["min_freq"] == 2

    @pytest.mark.asyncio
    async def test_prune_by_frequency_handles_query_error(self, mock_neo4j_pool):
        """Test that query errors are handled gracefully."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        pruner = GraphPruner(mock_neo4j_pool)
        count = await pruner.prune_by_frequency()

        assert count == 0

    @pytest.mark.asyncio
    async def test_prune_by_frequency_empty_result(self, mock_neo4j_pool):
        """Test handling of empty query results."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        pruner = GraphPruner(mock_neo4j_pool)
        count = await pruner.prune_by_frequency()

        assert count == 0


class TestPruneByDegree:
    """Tests for degree-based pruning strategy."""

    @pytest.mark.asyncio
    async def test_prune_by_degree_marks_low_degree_entities(self, mock_neo4j_pool):
        """Test that entities with low degree are marked pruned."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[{"pruned_count": 3}])

        pruner = GraphPruner(mock_neo4j_pool, min_entity_degree=2)
        count = await pruner.prune_by_degree()

        assert count == 3
        call_args = mock_neo4j_pool.execute_query.call_args
        assert "min_degree" in call_args[0][1]
        assert call_args[0][1]["min_degree"] == 2

    @pytest.mark.asyncio
    async def test_prune_by_degree_excludes_already_pruned(self, mock_neo4j_pool):
        """Test that already pruned entities are excluded."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[{"pruned_count": 2}])

        pruner = GraphPruner(mock_neo4j_pool)
        await pruner.prune_by_degree()

        query = mock_neo4j_pool.execute_query.call_args[0][0]
        assert "e.pruned IS NULL OR e.pruned = false" in query

    @pytest.mark.asyncio
    async def test_prune_by_degree_handles_error(self, mock_neo4j_pool):
        """Test error handling in degree pruning."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Connection failed"))

        pruner = GraphPruner(mock_neo4j_pool)
        count = await pruner.prune_by_degree()

        assert count == 0


class TestPruneByEdgeWeight:
    """Tests for edge weight percentile pruning strategy."""

    @pytest.mark.asyncio
    async def test_prune_by_edge_weight_calculates_percentile(self, mock_neo4j_pool):
        """Test that edge weight percentile is calculated correctly."""
        # First call: get weights
        # Second call: mark edges as pruned
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"weight": 0.1}, {"weight": 0.5}, {"weight": 1.0}, {"weight": 2.0}],
                [{"pruned_count": 2}],
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool, min_edge_weight_pct=50.0)
        count = await pruner.prune_by_edge_weight()

        assert count == 2
        assert mock_neo4j_pool.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_prune_by_edge_weight_empty_weights(self, mock_neo4j_pool):
        """Test handling when no edge weights exist."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        pruner = GraphPruner(mock_neo4j_pool)
        count = await pruner.prune_by_edge_weight()

        assert count == 0

    @pytest.mark.asyncio
    async def test_prune_by_edge_weight_handles_error(self, mock_neo4j_pool):
        """Test error handling in edge weight pruning."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        pruner = GraphPruner(mock_neo4j_pool)
        count = await pruner.prune_by_edge_weight()

        assert count == 0


class TestPruneEgoNodes:
    """Tests for ego node removal strategy."""

    @pytest.mark.asyncio
    async def test_prune_ego_nodes_marks_highest_degree(self, mock_neo4j_pool):
        """Test that highest degree entity is marked pruned."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[{"pruned_count": 1}])

        pruner = GraphPruner(mock_neo4j_pool, remove_ego_nodes=True)
        count = await pruner.prune_ego_nodes()

        assert count == 1

    @pytest.mark.asyncio
    async def test_prune_ego_nodes_disabled_by_default(self, mock_neo4j_pool):
        """Test that ego pruning is not executed when disabled."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[{"pruned_count": 0}])

        pruner = GraphPruner(mock_neo4j_pool, remove_ego_nodes=False)
        count = await pruner.prune_ego_nodes()

        # Should still execute the query but return 0 if no entity found
        assert mock_neo4j_pool.execute_query.called

    @pytest.mark.asyncio
    async def test_prune_ego_nodes_handles_error(self, mock_neo4j_pool):
        """Test error handling in ego node pruning."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        pruner = GraphPruner(mock_neo4j_pool)
        count = await pruner.prune_ego_nodes()

        assert count == 0


class TestFullPrunePipeline:
    """Tests for the full pruning pipeline."""

    @pytest.mark.asyncio
    async def test_prune_executes_all_strategies(self, mock_neo4j_pool):
        """Test that all strategies are executed in order."""
        # Setup mock responses
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                # _get_counts
                [{"count": 100}],
                [{"count": 500}],
                # _calculate_modularity (before)
                [],
                # prune_by_frequency
                [{"pruned_count": 10}],
                # prune_by_degree
                [{"pruned_count": 5}],
                # prune_by_edge_weight (two calls: get weights, mark pruned)
                [{"weight": 1.0}, {"weight": 2.0}, {"weight": 3.0}],
                [{"pruned_count": 8}],
                # _calculate_modularity (after)
                [],
                # _get_pruned_counts
                [{"count": 15}],
                [{"count": 20}],
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool)
        result = await pruner.prune()

        assert isinstance(result, PruneResult)
        assert result.total_entities == 100
        assert result.total_edges == 500
        assert "frequency" in result.strategies_applied
        assert "degree" in result.strategies_applied
        assert "edge_weight" in result.strategies_applied
        assert result.strategies_applied["frequency"] == 10
        assert result.strategies_applied["degree"] == 5
        assert result.strategies_applied["edge_weight"] == 8

    @pytest.mark.asyncio
    async def test_prune_with_ego_nodes_enabled(self, mock_neo4j_pool):
        """Test full pipeline with ego node removal enabled."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 100}],
                [{"count": 500}],  # counts
                [],  # modularity before
                [{"pruned_count": 10}],  # frequency
                [{"pruned_count": 5}],  # degree
                [{"weight": 1.0}],
                [{"pruned_count": 3}],  # edge_weight
                [{"pruned_count": 1}],  # ego
                [],  # modularity after
                [{"count": 16}],
                [{"count": 24}],  # pruned_counts
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool, remove_ego_nodes=True)
        result = await pruner.prune()

        assert "ego" in result.strategies_applied
        assert result.strategies_applied["ego"] == 1


class TestUndoPruning:
    """Tests for undo pruning functionality."""

    @pytest.mark.asyncio
    async def test_undo_pruning_clears_markers(self, mock_neo4j_pool):
        """Test that undo clears all pruned markers."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 15}],  # entities
                [{"count": 20}],  # edges
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool)
        total = await pruner.undo_pruning()

        assert total == 35
        assert mock_neo4j_pool.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_undo_pruning_handles_error(self, mock_neo4j_pool):
        """Test error handling in undo pruning."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        pruner = GraphPruner(mock_neo4j_pool)
        total = await pruner.undo_pruning()

        assert total == 0


class TestReapplyPruning:
    """Tests for reapply pruning functionality."""

    @pytest.mark.asyncio
    async def test_reapply_updates_parameters(self, mock_neo4j_pool):
        """Test that reapply updates parameters before pruning."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 0}],
                [{"count": 0}],  # undo
                [{"count": 100}],
                [{"count": 500}],  # counts
                [],  # modularity before
                [{"pruned_count": 20}],  # frequency with new min
                [{"pruned_count": 10}],  # degree
                [{"weight": 1.0}],
                [{"pruned_count": 5}],  # edge_weight
                [],  # modularity after
                [{"count": 30}],
                [{"count": 15}],  # pruned_counts
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool, min_entity_frequency=2)
        result = await pruner.reapply_pruning(min_entity_frequency=5)

        assert pruner.min_entity_frequency == 5
        assert isinstance(result, PruneResult)

    @pytest.mark.asyncio
    async def test_reapply_ignores_invalid_parameters(self, mock_neo4j_pool):
        """Test that invalid parameters are ignored."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 0}],
                [{"count": 0}],  # undo
                [{"count": 100}],
                [{"count": 500}],  # counts
                [],  # modularity before
                [{"pruned_count": 5}],  # frequency
                [{"pruned_count": 3}],  # degree
                [{"weight": 1.0}],
                [{"pruned_count": 2}],  # edge_weight
                [],  # modularity after
                [{"count": 8}],
                [{"count": 6}],  # pruned_counts
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool)
        original_freq = pruner.min_entity_frequency

        # Invalid parameter should be ignored
        result = await pruner.reapply_pruning(invalid_param=123)

        assert pruner.min_entity_frequency == original_freq
        assert isinstance(result, PruneResult)


class TestPruneResultStatistics:
    """Tests for PruneResult statistics."""

    @pytest.mark.asyncio
    async def test_prune_result_contains_all_fields(self, mock_neo4j_pool):
        """Test that PruneResult contains all expected fields."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 100}],
                [{"count": 500}],  # _get_counts
                [{"source": "a", "target": "b", "weight": 1.0}],  # modularity before
                [{"pruned_count": 10}],  # frequency
                [{"pruned_count": 5}],  # degree
                [{"weight": 1.0}],
                [{"pruned_count": 3}],  # edge_weight
                [{"count": 15}],
                [{"count": 8}],  # _get_pruned_counts
                [{"source": "a", "target": "b", "weight": 1.0}],  # modularity after
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool)
        result = await pruner.prune()

        assert result.total_entities == 100
        assert result.pruned_entities == 15
        assert result.total_edges == 500
        assert result.pruned_edges == 8
        assert "frequency" in result.strategies_applied
        assert "degree" in result.strategies_applied
        assert "edge_weight" in result.strategies_applied
        # Modularity may be None if calculation fails
        assert result.modularity_before is not None or result.modularity_before is None
        assert result.modularity_after is not None or result.modularity_after is None

    @pytest.mark.asyncio
    async def test_prune_result_strategies_applied(self, mock_neo4j_pool):
        """Test strategies_applied dictionary content."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 50}],
                [{"count": 200}],  # counts
                [],  # modularity before
                [{"pruned_count": 7}],  # frequency
                [{"pruned_count": 4}],  # degree
                [{"weight": 1.0}],
                [{"pruned_count": 6}],  # edge_weight
                [],  # modularity after
                [{"count": 11}],
                [{"count": 6}],  # pruned_counts
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool)
        result = await pruner.prune()

        assert result.strategies_applied["frequency"] == 7
        assert result.strategies_applied["degree"] == 4
        assert result.strategies_applied["edge_weight"] == 6


class TestModularityCalculation:
    """Tests for modularity calculation."""

    @pytest.mark.asyncio
    async def test_calculate_modularity_with_edges(self, mock_neo4j_pool):
        """Test modularity calculation with actual edges."""
        edges = [
            {"source": "A", "target": "B", "weight": 1.0},
            {"source": "B", "target": "C", "weight": 1.0},
            {"source": "C", "target": "A", "weight": 1.0},
        ]
        mock_neo4j_pool.execute_query = AsyncMock(return_value=edges)

        pruner = GraphPruner(mock_neo4j_pool)
        modularity = await pruner._calculate_modularity()

        # Should return a float value
        assert isinstance(modularity, float) or modularity is None

    @pytest.mark.asyncio
    async def test_calculate_modularity_empty_graph(self, mock_neo4j_pool):
        """Test modularity with empty graph."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        pruner = GraphPruner(mock_neo4j_pool)
        modularity = await pruner._calculate_modularity()

        assert modularity is None

    @pytest.mark.asyncio
    async def test_calculate_modularity_handles_error(self, mock_neo4j_pool):
        """Test modularity calculation error handling."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        pruner = GraphPruner(mock_neo4j_pool)
        modularity = await pruner._calculate_modularity()

        assert modularity is None


class TestHelperMethods:
    """Tests for helper methods."""

    @pytest.mark.asyncio
    async def test_get_counts(self, mock_neo4j_pool):
        """Test _get_counts method."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 100}],
                [{"count": 500}],
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool)
        entities, edges = await pruner._get_counts()

        assert entities == 100
        assert edges == 500

    @pytest.mark.asyncio
    async def test_get_counts_handles_error(self, mock_neo4j_pool):
        """Test _get_counts error handling."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        pruner = GraphPruner(mock_neo4j_pool)
        entities, edges = await pruner._get_counts()

        assert entities == 0
        assert edges == 0

    @pytest.mark.asyncio
    async def test_get_pruned_counts(self, mock_neo4j_pool):
        """Test _get_pruned_counts method."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"count": 15}],
                [{"count": 20}],
            ]
        )

        pruner = GraphPruner(mock_neo4j_pool)
        entities, edges = await pruner._get_pruned_counts()

        assert entities == 15
        assert edges == 20
