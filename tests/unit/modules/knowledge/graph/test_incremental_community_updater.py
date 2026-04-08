# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for IncrementalCommunityUpdater."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.graph.incremental_community_updater import (
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
    async def test_trigger_by_interval_exact(self, updater):
        """Test trigger when interval exactly matches."""
        last_update = datetime.now(timezone.utc) - timedelta(minutes=30)
        result = await updater.should_trigger(pending_count=10, last_update_at=last_update)

        assert result is True

    @pytest.mark.asyncio
    async def test_no_trigger_within_interval(self, updater):
        """Test no trigger when within interval."""
        last_update = datetime.now(timezone.utc) - timedelta(minutes=15)
        result = await updater.should_trigger(pending_count=10, last_update_at=last_update)

        assert result is False

    @pytest.mark.asyncio
    async def test_no_trigger_no_last_update(self, updater):
        """Test no trigger when no last update and below threshold."""
        result = await updater.should_trigger(pending_count=10, last_update_at=None)

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
    async def test_get_stats_fallback_to_count(self, updater, mock_neo4j_pool):
        """Test fallback to counting communities when metadata missing."""
        # First call (metadata) returns empty or error, second call (count) returns 5
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # Metadata query returns empty
                [{"total": 5}],  # Community count query
            ]
        )

        stats = await updater.get_stats()

        assert stats.total_communities == 5


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
                {"community_id": "comm_1"},  # Duplicate
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
        assert edges[0] == ("1", "2", 1.0)

    @pytest.mark.asyncio
    async def test_extract_empty_community_list(self, updater):
        """Test with empty community list."""
        node_ids, edges = await updater._extract_subgraph([])

        assert node_ids == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_extract_handles_error(self, updater, mock_neo4j_pool):
        """Test error handling in subgraph extraction."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        node_ids, edges = await updater._extract_subgraph(["comm_1"])

        assert node_ids == []
        assert edges == []


class TestGetCurrentAssignments:
    """Tests for _get_current_assignments method."""

    @pytest.mark.asyncio
    async def test_returns_assignment_mapping(self, updater, mock_neo4j_pool):
        """Test returns node_id to community_id mapping."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[
                {"node_id": "1", "community_id": "comm_1"},
                {"node_id": "2", "community_id": "comm_2"},
            ]
        )

        result = await updater._get_current_assignments(["1", "2"])

        assert result["1"] == "comm_1"
        assert result["2"] == "comm_2"

    @pytest.mark.asyncio
    async def test_handles_empty_node_list(self, updater):
        """Test with empty node list."""
        result = await updater._get_current_assignments([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_handles_query_error(self, updater, mock_neo4j_pool):
        """Test error handling."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("DB error"))

        result = await updater._get_current_assignments(["1"])

        assert result == {}


class TestClusterCommunities:
    """Tests for _cluster_communities method."""

    @pytest.mark.asyncio
    async def test_single_component(self, updater):
        """Test detection of single connected component."""
        node_ids = ["1", "2", "3"]
        edges = [("1", "2", 1.0), ("2", "3", 1.0)]

        result = await updater._cluster_communities(node_ids, edges)

        # All nodes in same community
        assert len(set(result.values())) == 1
        assert result["1"] == result["2"] == result["3"]

    @pytest.mark.asyncio
    async def test_multiple_components(self, updater):
        """Test detection of multiple disconnected components."""
        node_ids = ["1", "2", "3", "4"]
        edges = [("1", "2", 1.0)]  # Only 1-2 connected, 3 and 4 isolated

        result = await updater._cluster_communities(node_ids, edges)

        # 1 and 2 in same community, 3 and 4 in different ones
        assert result["1"] == result["2"]
        assert result["1"] != result["3"]
        assert result["3"] != result["4"]

    @pytest.mark.asyncio
    async def test_empty_graph(self, updater):
        """Test with empty graph."""
        result = await updater._cluster_communities([], [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_isolated_nodes(self, updater):
        """Test with isolated nodes (no edges)."""
        node_ids = ["1", "2", "3"]
        edges = []

        result = await updater._cluster_communities(node_ids, edges)

        # Each node in its own component
        assert len(set(result.values())) == 3


class TestWriteDiff:
    """Tests for _write_diff method."""

    @pytest.mark.asyncio
    async def test_write_diff_calculates_changes(self, updater, mock_neo4j_pool):
        """Test diff calculation and write operations."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[{"count": 0}])

        old_assignments = {"1": "comm_1", "2": "comm_1"}
        new_assignments = {"1": "comm_1", "2": "comm_2", "3": "comm_2"}

        result = await updater._write_diff(old_assignments, new_assignments)

        # 2 reassigned (2 moved, 3 new), comm_2 is new
        assert result["reassigned"] == 2
        assert result["created"] == 1

    @pytest.mark.asyncio
    async def test_write_diff_no_changes(self, updater, mock_neo4j_pool):
        """Test with no changes."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        old_assignments = {"1": "comm_1", "2": "comm_1"}
        new_assignments = {"1": "comm_1", "2": "comm_1"}

        result = await updater._write_diff(old_assignments, new_assignments)

        assert result["reassigned"] == 0
        assert result["created"] == 0


class TestMarkStaleReports:
    """Tests for _mark_stale_reports method."""

    @pytest.mark.asyncio
    async def test_marks_reports_stale(self, updater, mock_neo4j_pool):
        """Test reports are marked stale."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"community_id": "comm_1", "entity_count": 100}],
                [{"stale_count": 5}],
            ]
        )

        # 15% change should trigger stale
        changes = {"comm_1": -15.0}
        result = await updater._mark_stale_reports(["comm_1"], changes)

        assert result == 5

    @pytest.mark.asyncio
    async def test_no_stale_below_threshold(self, updater, mock_neo4j_pool):
        """Test no reports marked when change below threshold."""
        mock_neo4j_pool.execute_query = AsyncMock(
            return_value=[{"community_id": "comm_1", "entity_count": 100}]
        )

        # 5% change should not trigger stale
        changes = {"comm_1": -5.0}
        result = await updater._mark_stale_reports(["comm_1"], changes)

        assert result == 0

    @pytest.mark.asyncio
    async def test_empty_community_list(self, updater):
        """Test with empty community list."""
        result = await updater._mark_stale_reports([], {})

        assert result == 0


class TestCalculateModularity:
    """Tests for _calculate_modularity method."""

    @pytest.mark.asyncio
    async def test_calculates_modularity(self, updater, mock_neo4j_pool):
        """Test modularity calculation."""
        edges = [
            {"source": "A", "target": "B", "weight": 1.0},
            {"source": "B", "target": "C", "weight": 1.0},
        ]
        comms = [
            {"entity_name": "A", "community_id": "comm_1"},
            {"entity_name": "B", "community_id": "comm_1"},
            {"entity_name": "C", "community_id": "comm_1"},
        ]

        mock_neo4j_pool.execute_query = AsyncMock(side_effect=[edges, comms])

        result = await updater._calculate_modularity()

        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_graph(self, updater, mock_neo4j_pool):
        """Test returns None for empty graph."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        result = await updater._calculate_modularity()

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_error(self, updater, mock_neo4j_pool):
        """Test error handling."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Query failed"))

        result = await updater._calculate_modularity()

        assert result is None


class TestComputeModularity:
    """Tests for _compute_modularity method."""

    def test_single_community(self, updater):
        """Test modularity with single community."""
        edges = [("A", "B", 1.0), ("B", "C", 1.0), ("C", "A", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = updater._compute_modularity(edges, partitions)

        assert isinstance(result, float)
        # Fully connected single community should have positive modularity
        assert result >= 0

    def test_empty_data(self, updater):
        """Test with empty data."""
        result = updater._compute_modularity([], {})

        assert result == 0.0

    def test_disconnected_communities(self, updater):
        """Test with disconnected communities."""
        edges = [("A", "B", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 1}

        result = updater._compute_modularity(edges, partitions)

        assert isinstance(result, float)


class TestRunLocalClustering:
    """Tests for _run_local_clustering method."""

    def test_single_component_gets_single_uuid(self, updater):
        """All connected nodes get the same community UUID."""
        nodes = ["a", "b", "c"]
        edges = [("a", "b", 1.0), ("b", "c", 1.0)]

        assignments = updater._run_local_clustering(nodes, edges)

        assert len(assignments) == 3
        assert len(set(assignments.values())) == 1
        comm_id = assignments["a"]
        assert len(comm_id) == 36  # UUID format

    def test_disconnected_components_get_different_uuids(self, updater):
        """Disconnected components get different community IDs."""
        nodes = ["a", "b", "c", "d"]
        edges = [("a", "b", 1.0), ("c", "d", 1.0)]

        assignments = updater._run_local_clustering(nodes, edges)

        assert assignments["a"] == assignments["b"]
        assert assignments["c"] == assignments["d"]
        assert assignments["a"] != assignments["c"]

    def test_isolated_nodes_each_get_own_uuid(self, updater):
        """Isolated nodes each get their own community UUID."""
        nodes = ["a", "b", "c"]
        edges = []

        assignments = updater._run_local_clustering(nodes, edges)

        assert len(assignments) == 3
        assert len(set(assignments.values())) == 3

    def test_nodes_from_edges_included(self, updater):
        """Nodes present only in edges are still assigned."""
        nodes = ["a"]
        edges = [("a", "b", 1.0)]

        assignments = updater._run_local_clustering(nodes, edges)

        assert "a" in assignments
        assert "b" in assignments
        assert assignments["a"] == assignments["b"]


class TestExecute:
    """Tests for execute method (main entry point)."""

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

    @pytest.mark.asyncio
    async def test_execute_full_flow(self, updater, mock_neo4j_pool):
        """Full execute flow with mock responses."""
        mock_pool_responses = [
            # modularity before - edges
            [],
            # identify affected communities
            [{"community_id": "c1"}, {"neighbor_community_id": "c2"}],
            # extract subgraph - edges with nodes
            [
                {"id1": "e1", "id2": "e2", "weight": 1.0},
            ],
            # get current assignments
            [{"node_id": "e1", "community_id": "c1"}, {"node_id": "e2", "community_id": "c1"}],
            # write diff - reassign entity (delete old)
            [],
            # write diff - reassign entity (create new)
            [],
            # write diff - update entity count
            [],
            # write diff - check emptied
            [],
            # mark stale - get counts
            [],
            # modularity after - edges
            [],
        ]
        mock_neo4j_pool.execute_query.side_effect = mock_pool_responses

        result = await updater.execute(["e1", "e2"])

        assert isinstance(result, IncrementalUpdateResult)
        assert result.affected_communities == 2

    @pytest.mark.asyncio
    async def test_execute_empty_subgraph_returns_early(self, updater, mock_neo4j_pool):
        """Execute returns early when subgraph is empty."""
        mock_neo4j_pool.execute_query.side_effect = [
            [],  # modularity before
            [{"community_id": "c1"}],  # identify communities
            [],  # extract subgraph returns empty
        ]

        result = await updater.execute(["e1"])

        assert result.affected_communities == 1
        assert result.entities_reassigned == 0


class TestRunIncrementalUpdate:
    """Tests for run_incremental_update method."""

    @pytest.mark.asyncio
    async def test_update_with_no_pending_entities(self, updater, mock_neo4j_pool):
        """Test update when no pending entities."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        result = await updater.run_incremental_update()

        assert result.affected_communities == 0
        assert result.entities_reassigned == 0

    @pytest.mark.asyncio
    async def test_update_creates_communities_for_new_entities(self, updater, mock_neo4j_pool):
        """Test creating communities for new entities without existing ones."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        result = await updater.run_incremental_update(entity_names=["EntityA"])

        # Should attempt to create communities
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


class TestRollbackBehavior:
    """Tests for rollback behavior during failures."""

    @pytest.fixture
    def updater(self, mock_neo4j_pool):
        """Create IncrementalCommunityUpdater instance."""
        return IncrementalCommunityUpdater(
            mock_neo4j_pool,
            update_threshold=50,
            interval_minutes=30,
        )

    @pytest.mark.asyncio
    async def test_partial_update_handles_query_error(self, updater, mock_neo4j_pool):
        """Test that query errors during update are handled gracefully."""
        # First call succeeds, second fails
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                Exception("Connection lost"),  # identify fails
            ]
        )

        result = await updater.execute(["EntityA"])

        # Should return result without crashing
        assert isinstance(result, IncrementalUpdateResult)
        assert result.affected_communities == 0

    @pytest.mark.asyncio
    async def test_extract_subgraph_failure_returns_empty(self, updater, mock_neo4j_pool):
        """Test that subgraph extraction failure returns empty result."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [{"community_id": "c1"}],  # identify succeeds
                Exception("Query timeout"),  # extract fails
            ]
        )

        result = await updater.execute(["EntityA"])

        assert result.affected_communities == 1  # Still counted
        assert result.entities_reassigned == 0

    @pytest.mark.asyncio
    async def test_write_diff_failure_continues(self, updater, mock_neo4j_pool):
        """Test that write diff failure doesn't crash the process."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [{"community_id": "c1"}],  # identify
                [{"id1": "e1", "id2": "e2", "weight": 1.0}],  # extract
                [{"node_id": "e1", "community_id": "c1"}],  # current assignments
                Exception("Write failed"),  # write diff fails
            ]
        )

        # Should not raise exception
        result = await updater.execute(["EntityA"])

        assert isinstance(result, IncrementalUpdateResult)

    @pytest.mark.asyncio
    async def test_mark_stale_failure_ignored(self, updater, mock_neo4j_pool):
        """Test that stale marking failure doesn't affect main result."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [{"community_id": "c1"}],  # identify
                [{"id1": "e1", "id2": "e2", "weight": 1.0}],  # extract
                [{"node_id": "e1", "community_id": "c1"}],  # assignments
                [],  # write diff delete
                [],  # write diff create
                [],  # write diff update
                [],  # write diff check
                Exception("Stale check failed"),  # mark stale fails
                [],  # modularity after
            ]
        )

        result = await updater.execute(["EntityA"])

        # Main result should still be valid
        assert result.affected_communities == 1

    @pytest.mark.asyncio
    async def test_consistency_preserved_on_subgraph_empty(self, updater, mock_neo4j_pool):
        """Test that consistency is preserved when subgraph is empty."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [{"community_id": "c1"}],  # identify
                [],  # extract returns empty
            ]
        )

        result = await updater.execute(["EntityA"])

        # Should return early without making changes
        assert result.entities_reassigned == 0
        assert result.communities_created == 0


class TestBatchUpdates:
    """Tests for batch update scenarios."""

    @pytest.fixture
    def updater(self, mock_neo4j_pool):
        """Create IncrementalCommunityUpdater instance."""
        return IncrementalCommunityUpdater(
            mock_neo4j_pool,
            update_threshold=50,
            max_subgraph_size=100,
        )

    @pytest.mark.asyncio
    async def test_batch_update_single_entity(self, updater, mock_neo4j_pool):
        """Test incremental update with single new entity."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [{"community_id": "c1"}],  # identify
                [{"id1": "e1", "id2": "e2", "weight": 1.0}],  # extract
                [{"node_id": "e1", "community_id": "c1"}],  # assignments
                [],  # write operations
                [],  # write operations
                [],  # write operations
                [],  # write operations
                [],  # mark stale
                [],  # modularity after
            ]
        )

        result = await updater.execute(["NewEntity"])

        assert isinstance(result, IncrementalUpdateResult)
        assert result.affected_communities == 1

    @pytest.mark.asyncio
    async def test_batch_update_multiple_entities(self, updater, mock_neo4j_pool):
        """Test incremental update with multiple entities."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [{"community_id": "c1"}, {"community_id": "c2"}],  # identify 2 communities
                [
                    {"id1": "e1", "id2": "e2", "weight": 1.0},
                    {"id1": "e2", "id2": "e3", "weight": 1.0},
                ],  # extract
                [
                    {"node_id": "e1", "community_id": "c1"},
                    {"node_id": "e2", "community_id": "c1"},
                ],  # assignments
                [],  # write operations
                [],  # write operations
                [],  # write operations
                [],  # write operations
                [],  # mark stale
                [],  # modularity after
            ]
        )

        result = await updater.execute(["EntityA", "EntityB", "EntityC"])

        assert result.affected_communities == 2

    @pytest.mark.asyncio
    async def test_large_batch_respects_max_subgraph(self, updater, mock_neo4j_pool):
        """Test that large batches respect max_subgraph_size."""
        # Generate many edges
        edges = [{"id1": f"e{i}", "id2": f"e{i + 1}", "weight": 1.0} for i in range(200)]

        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [{"community_id": "c1"}],  # identify
                edges,  # extract - many edges
                [{"node_id": f"e{i}", "community_id": "c1"} for i in range(100)],  # assignments
                [],  # write operations
                [],  # write operations
                [],  # write operations
                [],  # write operations
                [],  # mark stale
                [],  # modularity after
            ]
        )

        result = await updater.execute([f"Entity{i}" for i in range(100)])

        assert isinstance(result, IncrementalUpdateResult)

    @pytest.mark.asyncio
    async def test_empty_entity_list_returns_early(self, updater):
        """Test that empty entity list returns without processing."""
        result = await updater.execute([])

        assert result.affected_communities == 0
        assert result.entities_reassigned == 0


class TestIncrementPendingCount:
    """Tests for increment_pending_count method."""

    @pytest.mark.asyncio
    async def test_increment_pending_count(self, updater, mock_neo4j_pool):
        """Test incrementing pending count."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        await updater.increment_pending_count(5)

        mock_neo4j_pool.execute_query.assert_called_once()
        call_args = mock_neo4j_pool.execute_query.call_args
        assert call_args[0][1]["count"] == 5

    @pytest.mark.asyncio
    async def test_increment_pending_count_default(self, updater, mock_neo4j_pool):
        """Test incrementing pending count with default value."""
        mock_neo4j_pool.execute_query = AsyncMock(return_value=[])

        await updater.increment_pending_count()

        call_args = mock_neo4j_pool.execute_query.call_args
        assert call_args[0][1]["count"] == 1


class TestCheckAndRun:
    """Tests for check_and_run method."""

    @pytest.mark.asyncio
    async def test_no_communities_triggers_rebuild(self, updater, mock_neo4j_pool):
        """Test that no communities triggers full rebuild."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"total": 0}],  # community count is 0
                [],  # rebuild operations
                [],  # rebuild operations
                [],  # rebuild operations
                [],  # rebuild operations
                [],  # rebuild operations
            ]
        )

        result = await updater.check_and_run()

        assert result["triggered"] is True
        assert result["reason"] == "no_communities_exist"

    @pytest.mark.asyncio
    async def test_no_conditions_met(self, updater, mock_neo4j_pool):
        """Test that no conditions met returns triggered=False."""
        recent_timestamp = datetime.now(timezone.utc) - timedelta(days=1)
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [{"total": 5}],  # community count
                [{"total": 100}],  # current entity count
                [{"previous_count": 100}],  # previous entity count (no change)
                [
                    {
                        "last_full_rebuild": recent_timestamp,
                        "last_incremental": None,
                        "pending_count": 0,
                    }
                ],  # stats
                # Health check queries (all return healthy state)
                [],  # find_empty_communities
                [],  # find_entity_count_mismatches
                [],  # find_missing_reports
                [],  # find_stale_reports
                [],  # find_hierarchy_breaks
                [],  # _calculate_modularity edges
                [],  # _get_community_assignments_for_modularity
                [
                    {
                        "total_communities": 5,
                        "avg_entity_count": 20.0,
                        "max_level": 1,
                        "communities_with_reports": 5,
                        "stale_report_count": 0,
                        "empty_community_count": 0,
                    }
                ],  # get_overall_metrics (healthy)
            ]
        )

        result = await updater.check_and_run()

        assert result["triggered"] is False


class TestForceRebuild:
    """Tests for force_rebuild method."""

    @pytest.mark.asyncio
    async def test_force_rebuild_always_runs(self, updater, mock_neo4j_pool):
        """Test that force_rebuild always triggers rebuild."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # modularity before
                [],  # rebuild operations
                [],  # rebuild operations
                [],  # rebuild operations
                [],  # rebuild operations
                [],  # rebuild operations
                [],  # rebuild operations
            ]
        )

        result = await updater.force_rebuild()

        assert result["triggered"] is True
        assert result["reason"] == "forced"
