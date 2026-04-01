# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for GraphPruner."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.graph.graph_pruner import GraphPruner, PruneResult


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4jPool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def pruner(mock_neo4j_pool):
    """Create GraphPruner instance with default parameters."""
    return GraphPruner(
        mock_neo4j_pool,
        min_entity_frequency=2,
        min_entity_degree=1,
        min_edge_weight_pct=40.0,
        remove_ego_nodes=False,
    )


class TestPruneResult:
    """Tests for PruneResult dataclass."""

    def test_default_initialization(self):
        """Test PruneResult initializes with defaults."""
        result = PruneResult()

        assert result.total_entities == 0
        assert result.pruned_entities == 0
        assert result.total_edges == 0
        assert result.pruned_edges == 0
        assert result.strategies_applied == {}
        assert result.modularity_before is None
        assert result.modularity_after is None

    def test_with_values(self):
        """Test PruneResult with values."""
        result = PruneResult(
            total_entities=100,
            pruned_entities=20,
            total_edges=500,
            pruned_edges=100,
            strategies_applied={"frequency": 10, "degree": 10},
            modularity_before=0.4,
            modularity_after=0.6,
        )

        assert result.total_entities == 100
        assert result.pruned_entities == 20
        assert result.total_edges == 500
        assert result.pruned_edges == 100
        assert result.strategies_applied["frequency"] == 10
        assert result.modularity_before == 0.4
        assert result.modularity_after == 0.6


class TestGraphPrunerInit:
    """Tests for GraphPruner initialization."""

    def test_default_parameters(self, mock_neo4j_pool):
        """Test pruner initializes with default parameters."""
        pruner = GraphPruner(mock_neo4j_pool)

        assert pruner.min_entity_frequency == 2
        assert pruner.min_entity_degree == 1
        assert pruner.min_edge_weight_pct == 40.0
        assert pruner.remove_ego_nodes is False

    def test_custom_parameters(self, mock_neo4j_pool):
        """Test pruner with custom parameters."""
        pruner = GraphPruner(
            mock_neo4j_pool,
            min_entity_frequency=5,
            min_entity_degree=2,
            min_edge_weight_pct=60.0,
            remove_ego_nodes=True,
        )

        assert pruner.min_entity_frequency == 5
        assert pruner.min_entity_degree == 2
        assert pruner.min_edge_weight_pct == 60.0
        assert pruner.remove_ego_nodes is True


class TestPrune:
    """Tests for prune method."""

    @pytest.mark.asyncio
    async def test_prune_returns_result(self, pruner, mock_neo4j_pool):
        """Test prune returns PruneResult."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 100}],  # total entities
            [{"count": 500}],  # total edges
            [],  # modularity before
            [{"pruned_count": 10}],  # frequency
            [{"pruned_count": 5}],  # degree
            [{"pruned_count": 20}],  # edge weight
            [{"count": 15}],  # pruned entities
            [{"count": 25}],  # pruned edges
            [],  # modularity after
        ]

        result = await pruner.prune()

        assert isinstance(result, PruneResult)
        assert result.total_entities == 100
        assert result.total_edges == 500

    @pytest.mark.asyncio
    async def test_prune_with_ego_nodes(self, mock_neo4j_pool):
        """Test prune with ego node removal enabled."""
        pruner = GraphPruner(mock_neo4j_pool, remove_ego_nodes=True)
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 100}],
            [{"count": 500}],
            [],
            [{"pruned_count": 10}],
            [{"pruned_count": 5}],
            [{"pruned_count": 20}],
            [{"pruned_count": 1}],  # ego
            [{"count": 16}],
            [{"count": 26}],
            [],
        ]

        result = await pruner.prune()

        assert "ego" in result.strategies_applied
        assert result.strategies_applied["ego"] == 1

    @pytest.mark.asyncio
    async def test_prune_handles_errors(self, pruner, mock_neo4j_pool):
        """Test prune handles errors gracefully."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        result = await pruner.prune()

        # Should return result with zeros
        assert isinstance(result, PruneResult)


class TestPruneByFrequency:
    """Tests for prune_by_frequency method."""

    @pytest.mark.asyncio
    async def test_prune_by_frequency_returns_count(self, pruner, mock_neo4j_pool):
        """Test prune_by_frequency returns count."""
        mock_neo4j_pool.execute_query.return_value = [{"pruned_count": 25}]

        result = await pruner.prune_by_frequency()

        assert result == 25

    @pytest.mark.asyncio
    async def test_prune_by_frequency_empty_result(self, pruner, mock_neo4j_pool):
        """Test prune_by_frequency handles empty result."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await pruner.prune_by_frequency()

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_by_frequency_handles_error(self, pruner, mock_neo4j_pool):
        """Test prune_by_frequency handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await pruner.prune_by_frequency()

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_by_frequency_uses_threshold(self, pruner, mock_neo4j_pool):
        """Test prune_by_frequency uses configured threshold."""
        mock_neo4j_pool.execute_query.return_value = [{"pruned_count": 10}]

        await pruner.prune_by_frequency()

        # Verify query was called with correct threshold
        call_args = mock_neo4j_pool.execute_query.call_args
        assert call_args[0][1]["min_freq"] == 2


class TestPruneByDegree:
    """Tests for prune_by_degree method."""

    @pytest.mark.asyncio
    async def test_prune_by_degree_returns_count(self, pruner, mock_neo4j_pool):
        """Test prune_by_degree returns count."""
        mock_neo4j_pool.execute_query.return_value = [{"pruned_count": 15}]

        result = await pruner.prune_by_degree()

        assert result == 15

    @pytest.mark.asyncio
    async def test_prune_by_degree_empty_result(self, pruner, mock_neo4j_pool):
        """Test prune_by_degree handles empty result."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await pruner.prune_by_degree()

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_by_degree_handles_error(self, pruner, mock_neo4j_pool):
        """Test prune_by_degree handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await pruner.prune_by_degree()

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_by_degree_uses_threshold(self, pruner, mock_neo4j_pool):
        """Test prune_by_degree uses configured threshold."""
        mock_neo4j_pool.execute_query.return_value = [{"pruned_count": 5}]

        await pruner.prune_by_degree()

        call_args = mock_neo4j_pool.execute_query.call_args
        assert call_args[0][1]["min_degree"] == 1


class TestPruneByEdgeWeight:
    """Tests for prune_by_edge_weight method."""

    @pytest.mark.asyncio
    async def test_prune_by_edge_weight_returns_count(self, pruner, mock_neo4j_pool):
        """Test prune_by_edge_weight returns count."""
        mock_neo4j_pool.execute_query.side_effect = [
            [  # weights query
                {"weight": 1.0},
                {"weight": 2.0},
                {"weight": 3.0},
                {"weight": 4.0},
                {"weight": 5.0},
            ],
            [{"pruned_count": 2}],  # prune query
        ]

        result = await pruner.prune_by_edge_weight()

        assert result == 2

    @pytest.mark.asyncio
    async def test_prune_by_edge_weight_empty_weights(self, pruner, mock_neo4j_pool):
        """Test prune_by_edge_weight with no edges."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await pruner.prune_by_edge_weight()

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_by_edge_weight_handles_error(self, pruner, mock_neo4j_pool):
        """Test prune_by_edge_weight handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await pruner.prune_by_edge_weight()

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_by_edge_weight_calculates_percentile(self, pruner, mock_neo4j_pool):
        """Test prune_by_edge_weight calculates percentile correctly."""
        mock_neo4j_pool.execute_query.side_effect = [
            [  # weights: 1, 2, 3, 4, 5 - 40th percentile is ~2.4
                {"weight": 1.0},
                {"weight": 2.0},
                {"weight": 3.0},
                {"weight": 4.0},
                {"weight": 5.0},
            ],
            [{"pruned_count": 2}],
        ]

        await pruner.prune_by_edge_weight()

        # Verify threshold was calculated and used
        prune_call = mock_neo4j_pool.execute_query.call_args_list[1]
        assert "threshold" in prune_call[0][1]


class TestPruneEgoNodes:
    """Tests for prune_ego_nodes method."""

    @pytest.mark.asyncio
    async def test_prune_ego_nodes_returns_count(self, pruner, mock_neo4j_pool):
        """Test prune_ego_nodes returns count."""
        mock_neo4j_pool.execute_query.return_value = [{"pruned_count": 1}]

        result = await pruner.prune_ego_nodes()

        assert result == 1

    @pytest.mark.asyncio
    async def test_prune_ego_nodes_empty_result(self, pruner, mock_neo4j_pool):
        """Test prune_ego_nodes handles empty result."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await pruner.prune_ego_nodes()

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_ego_nodes_handles_error(self, pruner, mock_neo4j_pool):
        """Test prune_ego_nodes handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await pruner.prune_ego_nodes()

        assert result == 0


class TestUndoPruning:
    """Tests for undo_pruning method."""

    @pytest.mark.asyncio
    async def test_undo_pruning_returns_total(self, pruner, mock_neo4j_pool):
        """Test undo_pruning returns total count."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 20}],  # entities
            [{"count": 30}],  # edges
        ]

        result = await pruner.undo_pruning()

        assert result == 50  # 20 + 30

    @pytest.mark.asyncio
    async def test_undo_pruning_empty_result(self, pruner, mock_neo4j_pool):
        """Test undo_pruning handles empty result."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await pruner.undo_pruning()

        assert result == 0

    @pytest.mark.asyncio
    async def test_undo_pruning_handles_error(self, pruner, mock_neo4j_pool):
        """Test undo_pruning handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await pruner.undo_pruning()

        assert result == 0


class TestReapplyPruning:
    """Tests for reapply_pruning method."""

    @pytest.mark.asyncio
    async def test_reapply_pruning_updates_params(self, pruner, mock_neo4j_pool):
        """Test reapply_pruning updates parameters."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 20}],  # undo entities
            [{"count": 30}],  # undo edges
            [{"count": 100}],  # total entities
            [{"count": 500}],  # total edges
            [],  # modularity before
            [{"pruned_count": 10}],
            [{"pruned_count": 5}],
            [{"pruned_count": 20}],
            [{"count": 15}],
            [{"count": 25}],
            [],
        ]

        result = await pruner.reapply_pruning(
            min_entity_frequency=5,
            min_entity_degree=2,
        )

        assert pruner.min_entity_frequency == 5
        assert pruner.min_entity_degree == 2

    @pytest.mark.asyncio
    async def test_reapply_pruning_ignores_invalid_params(self, pruner, mock_neo4j_pool):
        """Test reapply_pruning ignores invalid parameters."""
        original_freq = pruner.min_entity_frequency

        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 0}],
            [{"count": 0}],
            [{"count": 0}],
            [{"count": 0}],
            [],
            [{"pruned_count": 0}],
            [{"pruned_count": 0}],
            [{"pruned_count": 0}],
            [{"count": 0}],
            [{"count": 0}],
            [],
        ]

        await pruner.reapply_pruning(invalid_param=100)

        assert pruner.min_entity_frequency == original_freq


class TestGetCounts:
    """Tests for _get_counts method."""

    @pytest.mark.asyncio
    async def test_get_counts_returns_tuple(self, pruner, mock_neo4j_pool):
        """Test _get_counts returns tuple of counts."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 100}],  # entities
            [{"count": 500}],  # edges
        ]

        entities, edges = await pruner._get_counts()

        assert entities == 100
        assert edges == 500

    @pytest.mark.asyncio
    async def test_get_counts_handles_error(self, pruner, mock_neo4j_pool):
        """Test _get_counts handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        entities, edges = await pruner._get_counts()

        assert entities == 0
        assert edges == 0


class TestGetPrunedCounts:
    """Tests for _get_pruned_counts method."""

    @pytest.mark.asyncio
    async def test_get_pruned_counts_returns_tuple(self, pruner, mock_neo4j_pool):
        """Test _get_pruned_counts returns tuple of counts."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"count": 20}],  # pruned entities
            [{"count": 50}],  # pruned edges
        ]

        entities, edges = await pruner._get_pruned_counts()

        assert entities == 20
        assert edges == 50

    @pytest.mark.asyncio
    async def test_get_pruned_counts_handles_error(self, pruner, mock_neo4j_pool):
        """Test _get_pruned_counts handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        entities, edges = await pruner._get_pruned_counts()

        assert entities == 0
        assert edges == 0


class TestCalculateModularity:
    """Tests for _calculate_modularity method."""

    @pytest.mark.asyncio
    async def test_calculate_modularity_returns_float(self, pruner, mock_neo4j_pool):
        """Test _calculate_modularity returns float."""
        mock_neo4j_pool.execute_query.return_value = [
            {"source": "A", "target": "B", "weight": 1.0},
            {"source": "B", "target": "C", "weight": 1.0},
        ]

        result = await pruner._calculate_modularity()

        assert result is not None
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_calculate_modularity_empty_graph(self, pruner, mock_neo4j_pool):
        """Test _calculate_modularity with empty graph."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await pruner._calculate_modularity()

        assert result is None

    @pytest.mark.asyncio
    async def test_calculate_modularity_handles_error(self, pruner, mock_neo4j_pool):
        """Test _calculate_modularity handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await pruner._calculate_modularity()

        assert result is None


class TestGeneratePartitions:
    """Tests for _generate_partitions method."""

    def test_single_component(self, pruner):
        """Test partitions for single component."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0)]

        result = pruner._generate_partitions(edges)

        assert result["A"] == result["B"] == result["C"]

    def test_multiple_components(self, pruner):
        """Test partitions for multiple components."""
        edges = [
            ("A", "B", 1.0),
            ("C", "D", 1.0),  # Separate component
        ]

        result = pruner._generate_partitions(edges)

        assert result["A"] == result["B"]
        assert result["C"] == result["D"]
        assert result["A"] != result["C"]

    def test_empty_edges(self, pruner):
        """Test partitions with empty edges."""
        result = pruner._generate_partitions([])

        assert result == {}


class TestComputeModularity:
    """Tests for _compute_modularity method."""

    def test_compute_modularity_single_community(self, pruner):
        """Test modularity for single community."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = pruner._compute_modularity(edges, partitions)

        assert isinstance(result, float)

    def test_compute_modularity_separate_communities(self, pruner):
        """Test modularity for separate communities."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}

        result = pruner._compute_modularity(edges, partitions)

        # Separate communities should have positive modularity
        assert result > 0

    def test_compute_modularity_empty(self, pruner):
        """Test modularity with empty inputs."""
        result = pruner._compute_modularity([], {})

        assert result == 0.0

    def test_compute_modularity_zero_weight(self, pruner):
        """Test modularity with zero total weight."""
        edges = [("A", "B", 0.0)]
        partitions = {"A": 0, "B": 0}

        result = pruner._compute_modularity(edges, partitions)

        assert result == 0.0

    def test_compute_modularity_with_resolution(self, pruner):
        """Test modularity with custom resolution."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}

        result_default = pruner._compute_modularity(edges, partitions, resolution=1.0)
        result_high = pruner._compute_modularity(edges, partitions, resolution=2.0)

        # Higher resolution should generally give lower modularity
        assert isinstance(result_default, float)
        assert isinstance(result_high, float)
