# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for knowledge community Neo4jCommunityRepo."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.community.repo import Neo4jCommunityRepo


@pytest.fixture
def mock_pool():
    """Mock Neo4jPool."""
    pool = MagicMock()
    pool.execute_query = AsyncMock()
    return pool


@pytest.fixture
def repo(mock_pool):
    """Create Neo4jCommunityRepo instance."""
    return Neo4jCommunityRepo(mock_pool)


class TestNeo4jCommunityRepoInit:
    """Tests for Neo4jCommunityRepo initialization."""

    def test_init(self, mock_pool):
        """Test basic initialization."""
        repo = Neo4jCommunityRepo(mock_pool)
        assert repo._pool is mock_pool


class TestEnsureConstraints:
    """Tests for ensure_constraints method."""

    @pytest.mark.asyncio
    async def test_ensure_constraints_creates_all(self, repo, mock_pool):
        """Test ensure_constraints creates constraints and indexes."""
        await repo.ensure_constraints()

        # Should call execute_query for constraints and indexes
        assert mock_pool.execute_query.call_count >= 1

    @pytest.mark.asyncio
    async def test_ensure_constraints_handles_errors(self, repo, mock_pool):
        """Test ensure_constraints handles errors gracefully."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Constraint exists"))

        # Should not raise
        await repo.ensure_constraints()


class TestDeleteAllCommunities:
    """Tests for delete_all_communities method."""

    @pytest.mark.asyncio
    async def test_delete_all_returns_count(self, repo, mock_pool):
        """Test delete_all_communities returns deleted count."""
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 5}])

        result = await repo.delete_all_communities()

        assert result == 5

    @pytest.mark.asyncio
    async def test_delete_all_empty(self, repo, mock_pool):
        """Test delete_all_communities with no communities."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.delete_all_communities()

        assert result == 0


class TestCreateCommunity:
    """Tests for create_community method."""

    @pytest.mark.asyncio
    async def test_create_community_basic(self, repo, mock_pool):
        """Test create_community creates a community."""
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "test-id"}])

        result = await repo.create_community(
            community_id="test-id",
            title="Test Community",
            level=0,
        )

        assert result == "test-id"
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_community_with_parent(self, repo, mock_pool):
        """Test create_community with parent."""
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "child-id"}])

        result = await repo.create_community(
            community_id="child-id",
            title="Child Community",
            level=1,
            parent_id="parent-id",
        )

        assert result == "child-id"


class TestGetCommunity:
    """Tests for get_community method."""

    @pytest.mark.asyncio
    async def test_get_community_found(self, repo, mock_pool):
        """Test get_community returns community when found."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "test-id",
                    "title": "Test",
                    "level": 0,
                    "parent_id": None,
                    "entity_count": 10,
                    "rank": 1.0,
                    "period": "2024-01-01",
                    "modularity": 0.5,
                    "created_at": None,
                    "updated_at": None,
                    "entity_ids": [],
                }
            ]
        )

        result = await repo.get_community("test-id")

        assert result is not None
        assert result.id == "test-id"

    @pytest.mark.asyncio
    async def test_get_community_not_found(self, repo, mock_pool):
        """Test get_community returns None when not found."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.get_community("nonexistent")

        assert result is None


class TestListCommunities:
    """Tests for list_communities method."""

    @pytest.mark.asyncio
    async def test_list_communities_returns_list(self, repo, mock_pool):
        """Test list_communities returns list of communities."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"id": "comm-1", "title": "Community 1"},
                {"id": "comm-2", "title": "Community 2"},
            ]
        )

        result = await repo.list_communities()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_communities_empty(self, repo, mock_pool):
        """Test list_communities returns empty list."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.list_communities()

        assert result == []


class TestAddEntityToCommunity:
    """Tests for add_entity_to_community method."""

    @pytest.mark.asyncio
    async def test_add_entity(self, repo, mock_pool):
        """Test add_entity_to_community creates relationship."""
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "comm-id"}])

        result = await repo.add_entity_to_community(
            community_id="comm-id",
            entity_canonical_name="Entity1",
            entity_type="PERSON",
        )

        assert result is True
        mock_pool.execute_query.assert_called_once()


class TestCreateParentRelationship:
    """Tests for create_parent_relationship method."""

    @pytest.mark.asyncio
    async def test_create_parent_relationship(self, repo, mock_pool):
        """Test create_parent_relationship creates relationship."""
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "child-id"}])

        result = await repo.create_parent_relationship(
            child_id="child-id",
            parent_id="parent-id",
        )

        assert result is True


class TestMarkReportStale:
    """Tests for mark_report_stale method."""

    @pytest.mark.asyncio
    async def test_mark_report_stale(self, repo, mock_pool):
        """Test mark_report_stale updates report."""
        await repo.mark_report_stale("report-id")

        mock_pool.execute_query.assert_called_once()


class TestCountCommunities:
    """Tests for count_communities method."""

    @pytest.mark.asyncio
    async def test_count_all(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 5}])
        count = await repo.count_communities()
        assert count == 5

    @pytest.mark.asyncio
    async def test_count_by_level(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 3}])
        count = await repo.count_communities(level=0)
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_empty(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[])
        count = await repo.count_communities()
        assert count == 0


class TestAddEntitiesBatch:
    """Tests for add_entities_batch method."""

    @pytest.mark.asyncio
    async def test_empty_batch(self, repo, mock_pool):
        count = await repo.add_entities_batch([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_batch_success(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 2}])
        assignments = [
            {"community_id": "c1", "entity_name": "华为", "entity_type": "组织"},
            {"community_id": "c1", "entity_name": "小米", "entity_type": "组织"},
        ]
        count = await repo.add_entities_batch(assignments)
        assert count == 2


class TestCreateReport:
    """Tests for create_report method."""

    @pytest.mark.asyncio
    async def test_create_report_success(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "r-1"}])
        report_id = await repo.create_report(
            community_id="c-1",
            title="Test Report",
            summary="Summary",
            full_content="Full content",
            key_entities=["华为"],
            key_relationships=["合作"],
            rank=5.0,
        )
        assert report_id == "r-1"

    @pytest.mark.asyncio
    async def test_create_report_failure(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[])
        with pytest.raises(RuntimeError, match="Failed to create"):
            await repo.create_report(
                community_id="c-1",
                title="T",
                summary="S",
                full_content="C",
                key_entities=[],
                key_relationships=[],
            )


class TestGetReport:
    """Tests for get_report method."""

    @pytest.mark.asyncio
    async def test_get_report_found(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "r-1",
                    "community_id": "c-1",
                    "title": "Report",
                    "summary": "S",
                    "full_content": "C",
                    "key_entities": [],
                    "key_relationships": [],
                    "rank": 5.0,
                    "full_content_embedding": None,
                    "stale": False,
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        )
        report = await repo.get_report("c-1")
        assert report is not None
        assert report.title == "Report"

    @pytest.mark.asyncio
    async def test_get_report_not_found(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[])
        report = await repo.get_report("c-1")
        assert report is None


class TestUpdateReportEmbedding:
    """Tests for update_report_embedding method."""

    @pytest.mark.asyncio
    async def test_update_success(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[{"id": "r-1"}])
        result = await repo.update_report_embedding("r-1", [0.1, 0.2])
        assert result is True


class TestDeleteReport:
    """Tests for delete_report method."""

    @pytest.mark.asyncio
    async def test_delete_success(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[{"deleted": 1}])
        result = await repo.delete_report("c-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[])
        result = await repo.delete_report("c-1")
        assert result is False


class TestFindSimilarReports:
    """Tests for find_similar_reports method."""

    @pytest.mark.asyncio
    async def test_find_similar_with_level(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "r-1",
                    "community_id": "c-1",
                    "title": "Report",
                    "summary": "S",
                    "full_content": "C",
                    "key_entities": [],
                    "key_relationships": [],
                    "rank": 5.0,
                    "score": 0.95,
                },
            ]
        )
        results = await repo.find_similar_reports([0.1, 0.2], top_k=5, level=0)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_find_similar_no_level(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[])
        results = await repo.find_similar_reports([0.1], top_k=5)
        assert results == []


class TestGetCommunityMetrics:
    """Tests for get_community_metrics method."""

    @pytest.mark.asyncio
    async def test_metrics_found(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "total_communities": 10,
                    "levels": 3,
                    "avg_size": 5.0,
                    "max_size": 20,
                    "min_size": 1,
                    "leaf_count": 8,
                    "reports": 5,
                    "orphan_communities": 1,
                }
            ]
        )
        metrics = await repo.get_community_metrics()
        assert metrics["total_communities"] == 10

    @pytest.mark.asyncio
    async def test_metrics_empty(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(return_value=[])
        metrics = await repo.get_community_metrics()
        assert metrics["total_communities"] == 0


class TestGetLevelDistribution:
    """Tests for get_level_distribution method."""

    @pytest.mark.asyncio
    async def test_distribution(self, repo, mock_pool):
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"level": 0, "count": 8},
                {"level": 1, "count": 2},
            ]
        )
        dist = await repo.get_level_distribution()
        assert len(dist) == 2
        assert dist[0]["level"] == 0
