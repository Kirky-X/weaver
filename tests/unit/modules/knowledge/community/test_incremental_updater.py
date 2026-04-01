# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for knowledge community IncrementalCommunityUpdater."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.community.incremental_updater import (
    CommunityStats,
    IncrementalCommunityUpdater,
    IncrementalUpdateResult,
)


@pytest.fixture
def mock_neo4j_pool():
    """Mock Neo4jPool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def updater(mock_neo4j_pool):
    """Create IncrementalCommunityUpdater instance with default parameters."""
    return IncrementalCommunityUpdater(
        mock_neo4j_pool,
        update_threshold=50,
        interval_minutes=30,
        max_subgraph_size=2000,
        full_rebuild_interval_days=7,
    )


class TestIncrementalCommunityUpdaterInit:
    """Tests for IncrementalCommunityUpdater initialization."""

    def test_default_parameters(self, mock_neo4j_pool):
        """Test updater initializes with default parameters."""
        updater = IncrementalCommunityUpdater(mock_neo4j_pool)

        assert updater.update_threshold == 50
        assert updater.interval_minutes == 30
        assert updater.max_subgraph_size == 2000
        assert updater.full_rebuild_interval_days == 7

    def test_custom_parameters(self, mock_neo4j_pool):
        """Test updater with custom parameters."""
        updater = IncrementalCommunityUpdater(
            mock_neo4j_pool,
            update_threshold=100,
            interval_minutes=60,
            max_subgraph_size=5000,
            full_rebuild_interval_days=14,
        )

        assert updater.update_threshold == 100
        assert updater.interval_minutes == 60
        assert updater.max_subgraph_size == 5000
        assert updater.full_rebuild_interval_days == 14


class TestShouldTrigger:
    """Tests for should_trigger method."""

    @pytest.mark.asyncio
    async def test_trigger_by_threshold(self, updater):
        """Test trigger when pending count exceeds threshold."""
        result = await updater.should_trigger(pending_count=60, last_update_at=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_trigger_by_threshold_exact(self, updater):
        """Test trigger when pending count equals threshold."""
        result = await updater.should_trigger(pending_count=50, last_update_at=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_trigger_below_threshold(self, updater):
        """Test no trigger when below threshold."""
        result = await updater.should_trigger(pending_count=30, last_update_at=None)
        assert result is False

    @pytest.mark.asyncio
    async def test_trigger_by_interval(self, updater):
        """Test trigger when interval has elapsed."""
        last_update = datetime.now(timezone.utc) - timedelta(minutes=35)
        result = await updater.should_trigger(pending_count=10, last_update_at=last_update)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_trigger_within_interval(self, updater):
        """Test no trigger when within interval."""
        last_update = datetime.now(timezone.utc) - timedelta(minutes=15)
        result = await updater.should_trigger(pending_count=10, last_update_at=last_update)
        assert result is False


class TestGetStats:
    """Tests for get_stats method."""

    @pytest.mark.asyncio
    async def test_get_stats_returns_metadata(self, updater, mock_neo4j_pool):
        """Test stats are returned from metadata."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "last_full_rebuild": datetime.now(timezone.utc),
                    "last_incremental": datetime.now(timezone.utc),
                    "pending_count": 10,
                }
            ]
        )

        stats = await updater.get_stats()

        assert isinstance(stats, CommunityStats)
        assert stats.pending_entity_count == 10

    @pytest.mark.asyncio
    async def test_get_stats_handles_error(self, updater, mock_neo4j_pool):
        """Test get_stats handles errors gracefully."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        stats = await updater.get_stats()

        assert isinstance(stats, CommunityStats)
        assert stats.total_communities == 0


class TestCheckFullRebuildNeeded:
    """Tests for check_full_rebuild_needed method."""

    @pytest.mark.asyncio
    async def test_rebuild_needed_no_timestamp(self, updater, mock_neo4j_pool):
        """Test rebuild needed when no timestamp exists."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "last_full_rebuild": None,
                    "last_incremental": None,
                    "pending_count": 0,
                }
            ]
        )

        result = await updater.check_full_rebuild_needed()

        assert result is True

    @pytest.mark.asyncio
    async def test_rebuild_needed_interval_exceeded(self, updater, mock_neo4j_pool):
        """Test rebuild needed when interval exceeded."""
        old_timestamp = datetime.now(timezone.utc) - timedelta(days=10)
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "last_full_rebuild": old_timestamp,
                    "last_incremental": None,
                    "pending_count": 0,
                }
            ]
        )

        result = await updater.check_full_rebuild_needed()

        assert result is True

    @pytest.mark.asyncio
    async def test_no_rebuild_needed_within_interval(self, updater, mock_neo4j_pool):
        """Test no rebuild needed when within interval."""
        recent_timestamp = datetime.now(timezone.utc) - timedelta(days=3)
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "last_full_rebuild": recent_timestamp,
                    "last_incremental": None,
                    "pending_count": 0,
                }
            ]
        )

        result = await updater.check_full_rebuild_needed()

        assert result is False


class TestIdentifyAffectedCommunities:
    """Tests for _identify_affected_communities method."""

    @pytest.mark.asyncio
    async def test_identify_returns_community_ids(self, updater, mock_neo4j_pool):
        """Test affected communities are identified."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"community_id": "comm_1"},
                {"neighbor_community_id": "comm_2"},
            ]
        )

        result = await updater._identify_affected_communities(["EntityA", "EntityB"])

        assert len(result) == 2
        assert "comm_1" in result
        assert "comm_2" in result

    @pytest.mark.asyncio
    async def test_identify_empty_entity_list(self, updater):
        """Test with empty entity list."""
        result = await updater._identify_affected_communities([])
        assert result == []

    @pytest.mark.asyncio
    async def test_identify_handles_error(self, updater, mock_neo4j_pool):
        """Test error handling."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        result = await updater._identify_affected_communities(["EntityA"])
        assert result == []


class TestExtractSubgraph:
    """Tests for _extract_subgraph method."""

    @pytest.mark.asyncio
    async def test_extract_returns_nodes_and_edges(self, updater, mock_neo4j_pool):
        """Test subgraph extraction returns nodes and edges."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"id1": "1", "id2": "2", "weight": 1.0},
                {"id1": "2", "id2": "3", "weight": 0.5},
            ]
        )

        node_ids, edges = await updater._extract_subgraph(["comm_1"])

        assert len(node_ids) == 3
        assert len(edges) == 2

    @pytest.mark.asyncio
    async def test_extract_empty_community_list(self, updater):
        """Test with empty community list."""
        node_ids, edges = await updater._extract_subgraph([])

        assert node_ids == []
        assert edges == []


class TestRunLocalClustering:
    """Tests for _run_local_clustering method."""

    def test_single_component(self, updater):
        """Test detection of single connected component."""
        nodes = ["1", "2", "3"]
        edges = [("1", "2", 1.0), ("2", "3", 1.0)]

        result = updater._run_local_clustering(nodes, edges)

        assert len(result) == 3
        assert len(set(result.values())) == 1

    def test_multiple_components(self, updater):
        """Test detection of multiple disconnected components."""
        nodes = ["1", "2", "3", "4"]
        edges = [("1", "2", 1.0)]

        result = updater._run_local_clustering(nodes, edges)

        assert result["1"] == result["2"]
        assert result["1"] != result["3"]

    def test_empty_graph(self, updater):
        """Test with empty graph."""
        result = updater._run_local_clustering([], [])
        assert result == {}


class TestExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_execute_returns_empty_on_no_entities(self, updater):
        """Returns empty result when no entities provided."""
        result = await updater.execute([])

        assert result.affected_communities == 0
        assert result.entities_reassigned == 0

    @pytest.mark.asyncio
    async def test_execute_no_affected_communities(self, updater, mock_neo4j_pool):
        """Execute returns early when no affected communities found."""
        mock_neo4j_pool.execute_query.side_effect = [
            [],  # modularity before
            [],  # identify communities (empty)
        ]

        result = await updater.execute(["unknown_entity"])

        assert result.affected_communities == 0
        assert isinstance(result, IncrementalUpdateResult)


class TestIncrementalUpdateResult:
    """Tests for IncrementalUpdateResult dataclass."""

    def test_result_initialization(self):
        """Test result dataclass initializes with defaults."""
        result = IncrementalUpdateResult()

        assert result.affected_communities == 0
        assert result.entities_reassigned == 0
        assert result.communities_created == 0
        assert result.communities_emptied == 0
        assert result.reports_marked_stale == 0
        assert result.modularity_before is None
        assert result.modularity_after is None
        assert result.duration_seconds == 0.0

    def test_result_with_values(self):
        """Test result dataclass with values."""
        result = IncrementalUpdateResult(
            affected_communities=5,
            entities_reassigned=10,
            communities_created=2,
            communities_emptied=1,
            reports_marked_stale=20,
            modularity_before=0.5,
            modularity_after=0.6,
            duration_seconds=1.5,
        )

        assert result.affected_communities == 5
        assert result.entities_reassigned == 10
        assert result.communities_created == 2
        assert result.communities_emptied == 1
        assert result.reports_marked_stale == 20
        assert result.modularity_before == 0.5
        assert result.modularity_after == 0.6
        assert result.duration_seconds == 1.5


class TestCommunityStats:
    """Tests for CommunityStats dataclass."""

    def test_stats_initialization(self):
        """Test stats dataclass initializes with defaults."""
        stats = CommunityStats()

        assert stats.last_full_rebuild_at is None
        assert stats.last_incremental_update_at is None
        assert stats.pending_entity_count == 0
        assert stats.total_communities == 0
        assert stats.modularity_history == []

    def test_stats_with_values(self):
        """Test stats dataclass with values."""
        now = datetime.now(timezone.utc)
        stats = CommunityStats(
            last_full_rebuild_at=now,
            last_incremental_update_at=now,
            pending_entity_count=100,
            total_communities=50,
            modularity_history=[0.5, 0.6, 0.7],
        )

        assert stats.last_full_rebuild_at == now
        assert stats.pending_entity_count == 100
        assert stats.total_communities == 50
        assert len(stats.modularity_history) == 3


class TestCheckAndRun:
    """Tests for check_and_run method."""

    @pytest.mark.asyncio
    async def test_check_and_run_no_communities(self, updater, mock_neo4j_pool):
        """Test check_and_run when no communities exist."""
        # First call for _get_community_count returns 0
        mock_neo4j_pool.execute_query.return_value = []

        with patch.object(updater, "run_full_rebuild") as mock_rebuild:
            mock_rebuild.return_value = IncrementalUpdateResult(communities_created=5)

            result = await updater.check_and_run()

            assert result["triggered"] is True
            assert result["reason"] == "no_communities_exist"


class TestForceRebuild:
    """Tests for force_rebuild method."""

    @pytest.mark.asyncio
    async def test_force_rebuild_returns_result(self, updater, mock_neo4j_pool):
        """Test force_rebuild returns result."""
        with patch.object(updater, "run_full_rebuild") as mock_rebuild:
            mock_rebuild.return_value = IncrementalUpdateResult(
                communities_created=10,
                modularity_after=0.6,
            )

            result = await updater.force_rebuild()

            assert result["triggered"] is True
            assert result["reason"] == "forced"


class TestCheckEntityChange:
    """Tests for _check_entity_change method."""

    @pytest.mark.asyncio
    async def test_check_entity_change_exceeded(self, updater, mock_neo4j_pool):
        """Test entity change exceeds threshold."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"total": 100}],  # current count
            [{"previous_count": 50}],  # previous count
        ]

        exceeded, current, previous = await updater._check_entity_change()

        assert exceeded is True
        assert current == 100
        assert previous == 50

    @pytest.mark.asyncio
    async def test_check_entity_change_within_threshold(self, updater, mock_neo4j_pool):
        """Test entity change within threshold."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"total": 100}],  # current count
            [{"previous_count": 95}],  # previous count - 5% change
        ]

        exceeded, current, previous = await updater._check_entity_change()

        assert exceeded is False
        assert current == 100
        assert previous == 95

    @pytest.mark.asyncio
    async def test_check_entity_change_handles_error(self, updater, mock_neo4j_pool):
        """Test _check_entity_change handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        exceeded, current, previous = await updater._check_entity_change()

        assert exceeded is False


class TestGetPendingEntityNames:
    """Tests for _get_pending_entity_names method."""

    @pytest.mark.asyncio
    async def test_get_pending_entity_names_returns_list(self, updater, mock_neo4j_pool):
        """Test _get_pending_entity_names returns entity names."""
        mock_neo4j_pool.execute_query.return_value = [
            {"name": "Entity1"},
            {"name": "Entity2"},
        ]

        result = await updater._get_pending_entity_names()

        assert len(result) == 2
        assert "Entity1" in result

    @pytest.mark.asyncio
    async def test_get_pending_entity_names_handles_error(self, updater, mock_neo4j_pool):
        """Test _get_pending_entity_names handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await updater._get_pending_entity_names()

        assert result == []


class TestGetCurrentAssignments:
    """Tests for _get_current_assignments method."""

    @pytest.mark.asyncio
    async def test_get_current_assignments_returns_dict(self, updater, mock_neo4j_pool):
        """Test _get_current_assignments returns assignments."""
        mock_neo4j_pool.execute_query.return_value = [
            {"node_id": "1", "community_id": "comm_a"},
            {"node_id": "2", "community_id": "comm_b"},
        ]

        result = await updater._get_current_assignments(["1", "2"])

        assert result["1"] == "comm_a"
        assert result["2"] == "comm_b"

    @pytest.mark.asyncio
    async def test_get_current_assignments_empty_list(self, updater):
        """Test _get_current_assignments with empty list."""
        result = await updater._get_current_assignments([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_current_assignments_handles_error(self, updater, mock_neo4j_pool):
        """Test _get_current_assignments handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await updater._get_current_assignments(["1"])

        assert result == {}


class TestClusterCommunities:
    """Tests for _cluster_communities method."""

    @pytest.mark.asyncio
    async def test_cluster_with_connected_components(self, updater):
        """Test clustering with connected components fallback."""
        nodes = ["1", "2", "3"]
        edges = [("1", "2", 1.0), ("2", "3", 1.0)]

        # Mock leidenalg not available
        with patch("modules.knowledge.community.incremental_updater.LEIDEN_AVAILABLE", False):
            result = await updater._cluster_communities(nodes, edges)

            assert len(result) == 3
            # All connected nodes should have same community
            assert result["1"] == result["2"] == result["3"]

    @pytest.mark.asyncio
    async def test_cluster_empty_nodes(self, updater):
        """Test clustering with empty nodes."""
        result = await updater._cluster_communities([], [])

        assert result == {}


class TestClusterWithLeiden:
    """Tests for _cluster_with_leiden method."""

    def test_cluster_with_leiden_no_edges(self, updater):
        """Test Leiden clustering with no edges."""
        nodes = ["1", "2"]
        edges: list = []

        with patch("modules.knowledge.community.incremental_updater.LEIDEN_AVAILABLE", True):
            result = updater._cluster_with_leiden(nodes, edges)

            assert len(result) == 2
            # Each node should have its own community
            assert result["1"] != result["2"]

    def test_cluster_with_leiden_handles_error(self, updater):
        """Test Leiden clustering handles errors and falls back."""
        nodes = ["1", "2"]
        edges = [("1", "2", 1.0)]

        with patch("modules.knowledge.community.incremental_updater.LEIDEN_AVAILABLE", True):
            with patch("modules.knowledge.community.incremental_updater.ig") as mock_ig:
                mock_ig.Graph.side_effect = Exception("Graph error")

                result = updater._cluster_with_leiden(nodes, edges)

                # Should fall back to connected components
                assert len(result) == 2


class TestWriteDiff:
    """Tests for _write_diff method."""

    @pytest.mark.asyncio
    async def test_write_diff_detects_reassignments(self, updater, mock_neo4j_pool):
        """Test _write_diff detects reassignments."""
        old_assignments = {"1": "comm_a", "2": "comm_a"}
        new_assignments = {"1": "comm_b", "2": "comm_a"}

        mock_neo4j_pool.execute_query.return_value = []

        result = await updater._write_diff(old_assignments, new_assignments)

        assert result["reassigned"] == 1
        assert result["created"] == 1  # comm_b is new

    @pytest.mark.asyncio
    async def test_write_diff_detects_empty_communities(self, updater, mock_neo4j_pool):
        """Test _write_diff detects emptied communities."""
        old_assignments = {"1": "comm_a"}
        new_assignments = {"1": "comm_b"}

        # Mock for reassignment
        mock_neo4j_pool.execute_query.return_value = []

        result = await updater._write_diff(old_assignments, new_assignments)

        assert result["reassigned"] == 1


class TestMarkStaleReports:
    """Tests for _mark_stale_reports method."""

    @pytest.mark.asyncio
    async def test_mark_stale_reports_marks_reports(self, updater, mock_neo4j_pool):
        """Test _mark_stale_reports marks reports with >10% change."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"community_id": "comm_a", "entity_count": 10}],  # entity counts
            [{"stale_count": 5}],  # stale reports count
        ]

        result = await updater._mark_stale_reports(
            ["comm_a"],
            {"comm_a": -5},  # 50% change
        )

        assert result == 5

    @pytest.mark.asyncio
    async def test_mark_stale_reports_small_change(self, updater, mock_neo4j_pool):
        """Test _mark_stale_reports ignores small changes."""
        mock_neo4j_pool.execute_query.return_value = [
            {"community_id": "comm_a", "entity_count": 100}
        ]

        result = await updater._mark_stale_reports(
            ["comm_a"],
            {"comm_a": -5},  # 5% change < 10%
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_mark_stale_reports_empty_list(self, updater):
        """Test _mark_stale_reports with empty list."""
        result = await updater._mark_stale_reports([], {})

        assert result == 0


class TestComputeModularity:
    """Tests for _compute_modularity method."""

    def test_compute_modularity_with_partitions(self, updater):
        """Test _compute_modularity with valid partitions."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = updater._compute_modularity(edges, partitions)

        assert isinstance(result, float)

    def test_compute_modularity_empty_edges(self, updater):
        """Test _compute_modularity with empty edges."""
        result = updater._compute_modularity([], {"A": 0})

        assert result == 0.0

    def test_compute_modularity_empty_partitions(self, updater):
        """Test _compute_modularity with empty partitions."""
        edges = [("A", "B", 1.0)]
        result = updater._compute_modularity(edges, {})

        assert result == 0.0


class TestIncrementPendingCount:
    """Tests for increment_pending_count method."""

    @pytest.mark.asyncio
    async def test_increment_pending_count(self, updater, mock_neo4j_pool):
        """Test increment_pending_count updates count."""
        mock_neo4j_pool.execute_query.return_value = []

        await updater.increment_pending_count(5)

        mock_neo4j_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_increment_pending_count_handles_error(self, updater, mock_neo4j_pool):
        """Test increment_pending_count handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        # Should not raise
        await updater.increment_pending_count(5)


class TestCreateCommunitiesForEntities:
    """Tests for _create_communities_for_entities method."""

    @pytest.mark.asyncio
    async def test_create_communities_for_entities(self, updater, mock_neo4j_pool):
        """Test _create_communities_for_entities creates communities."""
        mock_neo4j_pool.execute_query.return_value = [
            {"entity": "Entity1", "neighbors": ["Entity2"]},
            {"entity": "Entity2", "neighbors": ["Entity1"]},
        ]

        result = await updater._create_communities_for_entities(["Entity1", "Entity2"])

        assert result >= 1  # At least one community created

    @pytest.mark.asyncio
    async def test_create_communities_empty_list(self, updater):
        """Test _create_communities_for_entities with empty list."""
        result = await updater._create_communities_for_entities([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_create_communities_handles_error(self, updater, mock_neo4j_pool):
        """Test _create_communities_for_entities handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("Query failed")

        result = await updater._create_communities_for_entities(["Entity1"])

        assert result == 0


class TestRunIncrementalUpdate:
    """Tests for run_incremental_update method."""

    @pytest.mark.asyncio
    async def test_run_incremental_update_no_pending(self, updater, mock_neo4j_pool):
        """Test run_incremental_update with no pending entities."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await updater.run_incremental_update()

        assert isinstance(result, IncrementalUpdateResult)
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_run_incremental_update_with_entities_no_affected(self, updater, mock_neo4j_pool):
        """Test run_incremental_update when no affected communities."""
        mock_neo4j_pool.execute_query.side_effect = [
            [],  # modularity before
            [],  # _create_communities_for_entities
        ]

        result = await updater.run_incremental_update(entity_names=["EntityA"])

        assert isinstance(result, IncrementalUpdateResult)

    @pytest.mark.asyncio
    async def test_run_incremental_update_with_full_flow(self, updater, mock_neo4j_pool):
        """Test run_incremental_update with full flow through all steps."""
        mock_neo4j_pool.execute_query.side_effect = [
            [],  # modularity before
            [{"community_id": "c1", "neighbor_community_id": None}],  # identify affected
            [{"id1": "n1", "id2": "n2", "weight": 1.0}],  # extract subgraph
            [{"node_id": "n1", "community_id": "old_c"}],  # current assignments
            [],  # write_diff (no empty communities)
            [],  # modularity after
            [],  # update metadata
        ]

        with patch("modules.knowledge.community.incremental_updater.LEIDEN_AVAILABLE", False):
            result = await updater.run_incremental_update(entity_names=["EntityA"])

        assert isinstance(result, IncrementalUpdateResult)
        assert result.affected_communities == 1

    @pytest.mark.asyncio
    async def test_run_incremental_update_empty_subgraph(self, updater, mock_neo4j_pool):
        """Test run_incremental_update when subgraph extraction returns empty."""
        mock_neo4j_pool.execute_query.side_effect = [
            [],  # modularity before
            [{"community_id": "c1", "neighbor_community_id": None}],  # identify affected
            [],  # extract subgraph (empty)
        ]

        result = await updater.run_incremental_update(entity_names=["EntityA"])

        assert isinstance(result, IncrementalUpdateResult)
        assert result.duration_seconds > 0


class TestExecuteFullFlow:
    """Tests for execute method full flow."""

    @pytest.mark.asyncio
    async def test_execute_with_affected_communities(self, updater, mock_neo4j_pool):
        """Test execute with full flow through affected communities."""
        mock_neo4j_pool.execute_query.side_effect = [
            [],  # modularity before
            [{"community_id": "c1", "neighbor_community_id": None}],  # identify affected
            [{"id1": "n1", "id2": "n2", "weight": 1.0}],  # extract subgraph
            [{"node_id": "n1", "community_id": "old_c"}],  # current assignments
            [],  # write_diff
            [],  # mark stale reports
            [],  # modularity after
        ]

        with patch("modules.knowledge.community.incremental_updater.LEIDEN_AVAILABLE", False):
            result = await updater.execute(["EntityA", "EntityB"])

        assert isinstance(result, IncrementalUpdateResult)
        assert result.affected_communities == 1

    @pytest.mark.asyncio
    async def test_execute_with_empty_subgraph(self, updater, mock_neo4j_pool):
        """Test execute when subgraph extraction returns empty."""
        mock_neo4j_pool.execute_query.side_effect = [
            [],  # modularity before
            [{"community_id": "c1", "neighbor_community_id": None}],  # identify affected
            [],  # extract subgraph (empty)
        ]

        result = await updater.execute(["EntityA"])

        assert isinstance(result, IncrementalUpdateResult)
        assert result.affected_communities == 1


class TestCheckAndRunFull:
    """Extended tests for check_and_run method."""

    @pytest.mark.asyncio
    async def test_check_and_run_entity_change_exceeded(self, updater, mock_neo4j_pool):
        """Test check_and_run when entity change exceeded."""
        mock_neo4j_pool.execute_query.side_effect = [
            [{"total": 1}],  # _get_community_count (has communities)
            [{"total": 100}],  # current entity count
            [{"previous_count": 50}],  # previous entity count
        ]

        with patch.object(updater, "run_full_rebuild") as mock_rebuild:
            mock_rebuild.return_value = IncrementalUpdateResult(communities_created=5)

            result = await updater.check_and_run()

            assert result["triggered"] is True
            assert result["reason"] == "entity_change_exceeded"

    @pytest.mark.asyncio
    async def test_check_and_run_interval_exceeded(self, updater, mock_neo4j_pool):
        """Test check_and_run when rebuild interval exceeded."""
        old_timestamp = datetime.now(timezone.utc) - timedelta(days=10)

        mock_neo4j_pool.execute_query.side_effect = [
            [{"total": 1}],  # _get_community_count
            [{"total": 100}],  # current entity count
            [{"previous_count": 98}],  # previous entity count (within threshold)
            # get_stats queries
            [
                {
                    "last_full_rebuild": old_timestamp,
                    "last_incremental": None,
                    "pending_count": 0,
                }
            ],
            [{"total": 5}],  # community count for get_stats
        ]

        with patch.object(updater, "run_full_rebuild") as mock_rebuild:
            mock_rebuild.return_value = IncrementalUpdateResult(communities_created=5)

            result = await updater.check_and_run()

            assert result["triggered"] is True
            assert result["reason"] == "rebuild_interval_exceeded"

    @pytest.mark.asyncio
    async def test_check_and_run_no_conditions_met(self, updater, mock_neo4j_pool):
        """Test check_and_run when no conditions are met."""
        recent_timestamp = datetime.now(timezone.utc) - timedelta(days=3)

        mock_neo4j_pool.execute_query.side_effect = [
            [{"total": 1}],  # _get_community_count
            [{"total": 100}],  # current entity count
            [{"previous_count": 98}],  # previous count (within threshold)
            # get_stats queries
            [
                {
                    "last_full_rebuild": recent_timestamp,
                    "last_incremental": None,
                    "pending_count": 0,
                }
            ],
            [{"total": 5}],  # community count for get_stats
        ]

        result = await updater.check_and_run()

        assert result["triggered"] is False
        assert result["reason"] is None


class TestRunFullRebuild:
    """Tests for run_full_rebuild method."""

    @pytest.mark.asyncio
    async def test_run_full_rebuild_delegates_to_detector(self, updater, mock_neo4j_pool):
        """Test run_full_rebuild delegates to CommunityDetector."""
        mock_detection_result = MagicMock()
        mock_detection_result.total_communities = 10
        mock_detection_result.total_entities = 50
        mock_detection_result.modularity = 0.65

        mock_neo4j_pool.execute_query.return_value = []

        with patch(
            "modules.knowledge.community.incremental_updater.IncrementalCommunityUpdater._calculate_modularity",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with patch(
                "modules.knowledge.community.detector.CommunityDetector.rebuild_communities",
                new_callable=AsyncMock,
                return_value=mock_detection_result,
            ):
                result = await updater.run_full_rebuild()

        assert isinstance(result, IncrementalUpdateResult)
        assert result.communities_created == 10
        assert result.entities_reassigned == 50
        assert result.duration_seconds > 0


class TestClusterWithLeiden:
    """Extended tests for Leiden clustering."""

    def test_cluster_with_leiden_with_edges(self, updater):
        """Test Leiden clustering with actual edges."""
        nodes = ["1", "2", "3"]
        edges = [("1", "2", 1.0), ("2", "3", 1.0)]

        with patch("modules.knowledge.community.incremental_updater.LEIDEN_AVAILABLE", True):
            with patch("modules.knowledge.community.incremental_updater.ig") as mock_ig:
                with patch("modules.knowledge.community.incremental_updater.leidenalg") as mock_la:
                    mock_graph = MagicMock()
                    mock_ig.Graph.return_value = mock_graph
                    mock_partition = MagicMock()
                    mock_partition.membership = [0, 0, 0]
                    mock_partition.q = 0.5
                    mock_la.find_partition.return_value = mock_partition
                    mock_la.ModularityVertexPartition = MagicMock()

                    result = updater._cluster_with_leiden(nodes, edges)

                    assert len(result) == 3
                    assert result["1"] == result["2"] == result["3"]


class TestClusterWithConnectedComponents:
    """Tests for _cluster_with_connected_components method."""

    def test_single_component_all_connected(self, updater):
        """All nodes connected form one community."""
        nodes = ["a", "b", "c"]
        edges = [("a", "b", 1.0), ("b", "c", 1.0)]

        result = updater._cluster_with_connected_components(nodes, edges)

        assert len(result) == 3
        assert len(set(result.values())) == 1

    def test_isolated_nodes_separate_communities(self, updater):
        """Isolated nodes each get their own community."""
        nodes = ["x", "y", "z"]
        edges: list[tuple[str, str, float]] = []

        result = updater._cluster_with_connected_components(nodes, edges)

        assert len(result) == 3
        assert len(set(result.values())) == 3

    def test_two_components(self, updater):
        """Two disconnected groups form two communities."""
        nodes = ["a", "b", "c", "d"]
        edges = [("a", "b", 1.0), ("c", "d", 1.0)]

        result = updater._cluster_with_connected_components(nodes, edges)

        assert result["a"] == result["b"]
        assert result["c"] == result["d"]
        assert result["a"] != result["c"]

    def test_empty_input(self, updater):
        """Empty nodes return empty dict."""
        result = updater._cluster_with_connected_components([], [])
        assert result == {}

    def test_edges_with_nodes_not_in_list(self, updater):
        """Edges referencing nodes not in the list are filtered."""
        nodes = ["a"]
        edges = [("a", "external", 1.0)]

        result = updater._cluster_with_connected_components(nodes, edges)

        assert len(result) == 1


class TestReassignEntity:
    """Tests for _reassign_entity method."""

    @pytest.mark.asyncio
    async def test_reassign_deletes_old_and_creates_new(self, updater, mock_neo4j_pool):
        """Test _reassign_entity deletes old and creates new relationship."""
        mock_neo4j_pool.execute_query.return_value = []

        await updater._reassign_entity("node_1", "old_comm", "new_comm")

        assert mock_neo4j_pool.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_reassign_no_old_community(self, updater, mock_neo4j_pool):
        """Test _reassign_entity with no old community only creates new."""
        mock_neo4j_pool.execute_query.return_value = []

        await updater._reassign_entity("node_1", None, "new_comm")

        # Only the create query should be called
        assert mock_neo4j_pool.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_reassign_handles_delete_error(self, updater, mock_neo4j_pool):
        """Test _reassign_entity handles delete error gracefully."""
        mock_neo4j_pool.execute_query.side_effect = [
            Exception("delete failed"),  # delete old relationship
            None,  # create new relationship
        ]

        await updater._reassign_entity("node_1", "old_comm", "new_comm")

        assert mock_neo4j_pool.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_reassign_handles_create_error(self, updater, mock_neo4j_pool):
        """Test _reassign_entity handles create error gracefully."""
        mock_neo4j_pool.execute_query.side_effect = [
            None,  # delete old
            Exception("create failed"),  # create new
        ]

        await updater._reassign_entity("node_1", "old_comm", "new_comm")

        assert mock_neo4j_pool.execute_query.call_count == 2


class TestMarkCommunityEmpty:
    """Tests for _mark_community_empty method."""

    @pytest.mark.asyncio
    async def test_mark_community_empty_success(self, updater, mock_neo4j_pool):
        """Test _mark_community_empty marks community."""
        mock_neo4j_pool.execute_query.return_value = []

        await updater._mark_community_empty("comm_123")

        mock_neo4j_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_community_empty_handles_error(self, updater, mock_neo4j_pool):
        """Test _mark_community_empty handles error."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        await updater._mark_community_empty("comm_123")

        mock_neo4j_pool.execute_query.assert_called_once()


class TestDeleteAllCommunities:
    """Tests for _delete_all_communities method."""

    @pytest.mark.asyncio
    async def test_delete_all_communities_success(self, updater, mock_neo4j_pool):
        """Test _delete_all_communities executes query."""
        mock_neo4j_pool.execute_query.return_value = []

        await updater._delete_all_communities()

        mock_neo4j_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_all_communities_handles_error(self, updater, mock_neo4j_pool):
        """Test _delete_all_communities handles error."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        await updater._delete_all_communities()

        mock_neo4j_pool.execute_query.assert_called_once()


class TestCalculateModularity:
    """Tests for _calculate_modularity method."""

    @pytest.mark.asyncio
    async def test_calculate_modularity_no_edges(self, updater, mock_neo4j_pool):
        """Test _calculate_modularity returns None when no edges."""
        mock_neo4j_pool.execute_query.return_value = []

        result = await updater._calculate_modularity()

        assert result is None

    @pytest.mark.asyncio
    async def test_calculate_modularity_with_edges(self, updater, mock_neo4j_pool):
        """Test _calculate_modularity computes modularity."""
        mock_neo4j_pool.execute_query.side_effect = [
            [  # edges query
                {"source": "A", "target": "B", "weight": 1.0},
                {"source": "B", "target": "C", "weight": 1.0},
            ],
            [  # community assignments
                {"entity_name": "A", "community_id": "c1"},
                {"entity_name": "B", "community_id": "c1"},
                {"entity_name": "C", "community_id": "c1"},
            ],
        ]

        result = await updater._calculate_modularity()

        assert isinstance(result, float)
        # All nodes in same community with 2 edges: modularity = 0
        # because degree_sums_within = 4, degree_sums_for = 4
        # Q = (4 - 1 * 16/4) / 4 = (4-4)/4 = 0
        # This is mathematically correct for a single community
        assert result >= 0.0

    @pytest.mark.asyncio
    async def test_calculate_modularity_handles_error(self, updater, mock_neo4j_pool):
        """Test _calculate_modularity handles errors."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        result = await updater._calculate_modularity()

        assert result is None


class TestComputeModularityExtended:
    """Extended tests for _compute_modularity method."""

    def test_compute_modularity_separate_communities(self, updater):
        """Test modularity with separate communities."""
        edges = [("A", "B", 1.0), ("C", "D", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}

        result = updater._compute_modularity(edges, partitions)

        assert result > 0.0

    def test_compute_modularity_zero_weight(self, updater):
        """Test modularity with zero total weight."""
        edges = [("A", "B", 0.0)]
        partitions = {"A": 0, "B": 0}

        result = updater._compute_modularity(edges, partitions)

        assert result == 0.0

    def test_compute_modularity_mixed_partitions(self, updater):
        """Test modularity with some nodes in partitions and some not."""
        edges = [("A", "B", 1.0), ("A", "C", 1.0)]
        partitions = {"A": 0}

        result = updater._compute_modularity(edges, partitions)

        assert isinstance(result, float)

    def test_compute_modularity_with_resolution(self, updater):
        """Test modularity with custom resolution parameter."""
        edges = [("A", "B", 1.0)]
        partitions = {"A": 0, "B": 0}

        result = updater._compute_modularity(edges, partitions, resolution=2.0)

        assert isinstance(result, float)


class TestGetCommunityAssignmentsForModularity:
    """Tests for _get_community_assignments_for_modularity method."""

    @pytest.mark.asyncio
    async def test_assignments_mapping(self, updater, mock_neo4j_pool):
        """Test community assignments are mapped to integers."""
        mock_neo4j_pool.execute_query.return_value = [
            {"entity_name": "A", "community_id": "c1"},
            {"entity_name": "B", "community_id": "c1"},
            {"entity_name": "C", "community_id": "c2"},
        ]

        result = await updater._get_community_assignments_for_modularity()

        assert result["A"] == result["B"]
        assert result["A"] != result["C"]

    @pytest.mark.asyncio
    async def test_assignments_handles_error(self, updater, mock_neo4j_pool):
        """Test error handling returns empty dict."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        result = await updater._get_community_assignments_for_modularity()

        assert result == {}

    @pytest.mark.asyncio
    async def test_assignments_skips_none_entries(self, updater, mock_neo4j_pool):
        """Test entries with None values are skipped."""
        mock_neo4j_pool.execute_query.return_value = [
            {"entity_name": "A", "community_id": "c1"},
            {"entity_name": None, "community_id": "c2"},
            {"entity_name": "B", "community_id": None},
        ]

        result = await updater._get_community_assignments_for_modularity()

        assert "A" in result
        assert len(result) == 1


class TestUpdateMetadata:
    """Tests for _update_metadata method."""

    @pytest.mark.asyncio
    async def test_update_metadata_success(self, updater, mock_neo4j_pool):
        """Test _update_metadata executes query."""
        mock_neo4j_pool.execute_query.return_value = []
        result_data = IncrementalUpdateResult()

        await updater._update_metadata(result_data)

        mock_neo4j_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_metadata_handles_error(self, updater, mock_neo4j_pool):
        """Test _update_metadata handles error."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")
        result_data = IncrementalUpdateResult()

        await updater._update_metadata(result_data)

        mock_neo4j_pool.execute_query.assert_called_once()


class TestUpdateFullRebuildMetadata:
    """Tests for _update_full_rebuild_metadata method."""

    @pytest.mark.asyncio
    async def test_update_full_rebuild_metadata(self, updater, mock_neo4j_pool):
        """Test _update_full_rebuild_metadata updates entity count."""
        mock_neo4j_pool.execute_query.return_value = []

        await updater._update_full_rebuild_metadata()

        assert mock_neo4j_pool.execute_query.call_count == 2


class TestCheckFullRebuildNeededExtended:
    """Extended tests for check_full_rebuild_needed."""

    @pytest.mark.asyncio
    async def test_rebuild_needed_modularity_degradation(self, updater, mock_neo4j_pool):
        """Test rebuild needed when modularity degrades."""
        old_timestamp = datetime.now(timezone.utc) - timedelta(days=3)

        # Modularity history: [0.8, 0.6, 0.5] -> drop of 0.3 > 0.05
        mock_neo4j_pool.execute_query.side_effect = [
            [
                {
                    "last_full_rebuild": old_timestamp,
                    "last_incremental": None,
                    "pending_count": 0,
                }
            ],
            [{"total": 5}],  # community count
        ]

        updater_instance = updater
        # We need to inject modularity_history somehow
        # Since get_stats reads from Neo4j, and modularity_history is a field,
        # we patch get_stats to return a CommunityStats with modularity_history
        from modules.knowledge.community.incremental_updater import CommunityStats

        stats = CommunityStats(
            last_full_rebuild_at=old_timestamp,
            modularity_history=[0.8, 0.6, 0.5],
        )

        with patch.object(updater, "get_stats", new_callable=AsyncMock, return_value=stats):
            result = await updater.check_full_rebuild_needed()

        assert result is True


class TestCreateCommunityWithEntities:
    """Tests for _create_community_with_entities method."""

    @pytest.mark.asyncio
    async def test_create_community_with_entities_success(self, updater, mock_neo4j_pool):
        """Test _create_community_with_entities executes query."""
        mock_neo4j_pool.execute_query.return_value = []

        await updater._create_community_with_entities("comm_123", ["Entity1", "Entity2"])

        mock_neo4j_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_community_with_entities_handles_error(self, updater, mock_neo4j_pool):
        """Test _create_community_with_entities handles error."""
        mock_neo4j_pool.execute_query.side_effect = Exception("DB error")

        await updater._create_community_with_entities("comm_123", ["Entity1"])

        mock_neo4j_pool.execute_query.assert_called_once()


class TestWriteDiffExtended:
    """Extended tests for _write_diff method."""

    @pytest.mark.asyncio
    async def test_write_diff_with_empty_communities(self, updater, mock_neo4j_pool):
        """Test _write_diff detects empty communities."""
        old_assignments = {"1": "comm_a"}
        new_assignments = {"1": "comm_b"}

        # Mock for reassignment delete+create queries and empty community check
        mock_neo4j_pool.execute_query.side_effect = [
            None,  # delete old relationship
            None,  # create new relationship
            [{"count": 0}],  # count entities in comm_a -> empty
            None,  # mark community empty
        ]

        result = await updater._write_diff(old_assignments, new_assignments)

        assert result["reassigned"] == 1
        assert result["emptied"] == 1

    @pytest.mark.asyncio
    async def test_write_diff_no_changes(self, updater, mock_neo4j_pool):
        """Test _write_diff with no changes."""
        assignments = {"1": "comm_a", "2": "comm_b"}

        result = await updater._write_diff(assignments, assignments)

        assert result["reassigned"] == 0
        assert result["created"] == 0
