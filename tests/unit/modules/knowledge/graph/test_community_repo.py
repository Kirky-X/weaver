# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4jCommunityRepo - Schema migration and CRUD operations."""

import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from modules.knowledge.graph.community_models import Community, CommunityReport
from modules.knowledge.graph.community_repo import Neo4jCommunityRepo


class TestNeo4jCommunityRepoInit:
    """Test Neo4jCommunityRepo initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        repo = Neo4jCommunityRepo(mock_pool)
        assert repo._pool == mock_pool


class TestNeo4jCommunityRepoEnsureConstraints:
    """Test ensure_constraints method for schema migration."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_ensure_constraints_creates_community_id_unique(self, repo):
        """Test that community ID uniqueness constraint is created."""
        await repo.ensure_constraints()

        calls = repo._pool.execute_query.call_args_list
        constraint_calls = [c for c in calls if "CREATE CONSTRAINT community_id_unique" in str(c)]
        assert len(constraint_calls) >= 1

    @pytest.mark.asyncio
    async def test_ensure_constraints_creates_community_report_id_unique(self, repo):
        """Test that community report ID uniqueness constraint is created."""
        await repo.ensure_constraints()

        calls = repo._pool.execute_query.call_args_list
        constraint_calls = [
            c for c in calls if "CREATE CONSTRAINT community_report_id_unique" in str(c)
        ]
        assert len(constraint_calls) >= 1

    @pytest.mark.asyncio
    async def test_ensure_constraints_creates_level_index(self, repo):
        """Test that community level index is created."""
        await repo.ensure_constraints()

        calls = repo._pool.execute_query.call_args_list
        index_calls = [c for c in calls if "community_level_index" in str(c)]
        assert len(index_calls) >= 1

    @pytest.mark.asyncio
    async def test_ensure_constraints_creates_period_index(self, repo):
        """Test that community period index is created."""
        await repo.ensure_constraints()

        calls = repo._pool.execute_query.call_args_list
        index_calls = [c for c in calls if "community_period_index" in str(c)]
        assert len(index_calls) >= 1

    @pytest.mark.asyncio
    async def test_ensure_constraints_creates_report_community_id_index(self, repo):
        """Test that community report community_id index is created."""
        await repo.ensure_constraints()

        calls = repo._pool.execute_query.call_args_list
        index_calls = [c for c in calls if "community_report_community_id_index" in str(c)]
        assert len(index_calls) >= 1

    @pytest.mark.asyncio
    async def test_ensure_constraints_uses_if_not_exists(self, repo):
        """Test that constraints use IF NOT EXISTS to avoid errors on re-run."""
        await repo.ensure_constraints()

        calls = repo._pool.execute_query.call_args_list
        all_calls_str = str(calls)

        # Check that IF NOT EXISTS is used in constraint creation
        assert "IF NOT EXISTS" in all_calls_str

    @pytest.mark.asyncio
    async def test_ensure_constraints_is_idempotent(self, repo):
        """Test that ensure_constraints can be called multiple times safely."""
        # First call
        await repo.ensure_constraints()
        first_call_count = repo._pool.execute_query.call_count

        # Reset mock
        repo._pool.execute_query.reset_mock()

        # Second call should work without errors
        await repo.ensure_constraints()
        second_call_count = repo._pool.execute_query.call_count

        # Both calls should execute the same number of queries
        assert first_call_count == second_call_count

    @pytest.mark.asyncio
    async def test_ensure_constraints_handles_errors_gracefully(self, repo):
        """Test that constraint creation handles errors (e.g., already exists)."""
        # Simulate an error (constraint already exists)
        repo._pool.execute_query = AsyncMock(side_effect=Exception("Constraint already exists"))

        # Should not raise - errors are caught and logged
        await repo.ensure_constraints()


class TestNeo4jCommunityRepoCreateCommunity:
    """Test create_community method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"id": "test-community-id"}])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_create_community_returns_id(self, repo):
        """Test that create_community returns the community ID."""
        community_id = str(uuid.uuid4())
        # Update mock to return the same ID we pass in
        repo._pool.execute_query = AsyncMock(return_value=[{"id": community_id}])
        result = await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=0,
        )
        assert result == community_id

    @pytest.mark.asyncio
    async def test_create_community_with_all_params(self, repo):
        """Test create_community with all parameters."""
        community_id = str(uuid.uuid4())
        parent_id = str(uuid.uuid4())

        await repo.create_community(
            community_id=community_id,
            title="Test Community",
            level=1,
            parent_id=parent_id,
            entity_count=10,
            rank=5.5,
            period="2026-03-24",
            modularity=0.45,
        )

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]  # Second argument is params dict

        assert params["id"] == community_id
        assert params["title"] == "Test Community"
        assert params["level"] == 1
        assert params["parent_id"] == parent_id
        assert params["entity_count"] == 10
        assert params["rank"] == 5.5
        assert params["period"] == "2026-03-24"
        assert params["modularity"] == 0.45

    @pytest.mark.asyncio
    async def test_create_community_raises_on_failure(self, repo):
        """Test that create_community raises when query fails."""
        repo._pool.execute_query = AsyncMock(return_value=None)

        with pytest.raises(RuntimeError, match="Failed to create community"):
            await repo.create_community(
                community_id=str(uuid.uuid4()),
                title="Test",
                level=0,
            )


class TestNeo4jCommunityRepoAddEntityToCommunity:
    """Test add_entity_to_community method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"id": "community-id"}])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_add_entity_to_community_returns_true(self, repo):
        """Test that add_entity_to_community returns True on success."""
        result = await repo.add_entity_to_community(
            community_id="community-id",
            entity_canonical_name="OpenAI",
            entity_type="组织机构",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_add_entity_to_community_returns_false_on_no_match(self, repo):
        """Test that add_entity_to_community returns False when no match."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        result = await repo.add_entity_to_community(
            community_id="non-existent",
            entity_canonical_name="NonExistent",
            entity_type="未知",
        )
        assert result is False


class TestNeo4jCommunityRepoAddEntitiesBatch:
    """Test add_entities_batch method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"total": 3}])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_add_entities_batch_returns_count(self, repo):
        """Test that add_entities_batch returns count of relationships created."""
        assignments = [
            {"community_id": "c1", "entity_name": "E1", "entity_type": "人物"},
            {"community_id": "c1", "entity_name": "E2", "entity_type": "组织机构"},
            {"community_id": "c2", "entity_name": "E3", "entity_type": "地点"},
        ]

        result = await repo.add_entities_batch(assignments)
        assert result == 3

    @pytest.mark.asyncio
    async def test_add_entities_batch_empty_list(self, repo):
        """Test that add_entities_batch returns 0 for empty list."""
        result = await repo.add_entities_batch([])
        assert result == 0


class TestNeo4jCommunityRepoCreateParentRelationship:
    """Test create_parent_relationship method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"id": "child-id"}])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_create_parent_relationship_returns_true(self, repo):
        """Test that create_parent_relationship returns True on success."""
        result = await repo.create_parent_relationship(
            child_id="child-id",
            parent_id="parent-id",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_create_parent_relationship_returns_false_on_no_match(self, repo):
        """Test that create_parent_relationship returns False when no match."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        result = await repo.create_parent_relationship(
            child_id="non-existent",
            parent_id="parent-id",
        )
        assert result is False


class TestNeo4jCommunityRepoDeleteAllCommunities:
    """Test delete_all_communities method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"total": 10}])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_delete_all_communities_returns_count(self, repo):
        """Test that delete_all_communities returns count of deleted communities."""
        result = await repo.delete_all_communities()
        assert result == 10

    @pytest.mark.asyncio
    async def test_delete_all_communities_returns_zero_on_empty(self, repo):
        """Test that delete_all_communities returns 0 when no communities."""
        repo._pool.execute_query = AsyncMock(return_value=None)
        result = await repo.delete_all_communities()
        assert result == 0


class TestNeo4jCommunityRepoGetCommunity:
    """Test get_community method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "test-id",
                    "title": "Test Community",
                    "level": 0,
                    "parent_id": None,
                    "entity_count": 5,
                    "rank": 3.5,
                    "period": "2026-03-24",
                    "modularity": 0.45,
                    "created_at": None,
                    "updated_at": None,
                    "entity_ids": ["E1", "E2"],
                }
            ]
        )
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_get_community_returns_community(self, repo):
        """Test that get_community returns Community instance."""
        result = await repo.get_community("test-id")

        assert result is not None
        assert isinstance(result, Community)
        assert result.id == "test-id"
        assert result.title == "Test Community"
        assert result.level == 0

    @pytest.mark.asyncio
    async def test_get_community_returns_none_on_not_found(self, repo):
        """Test that get_community returns None when not found."""
        repo._pool.execute_query = AsyncMock(return_value=[])
        result = await repo.get_community("non-existent")
        assert result is None


class TestNeo4jCommunityRepoListCommunities:
    """Test list_communities method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "c1",
                    "title": "C1",
                    "level": 0,
                    "parent_id": None,
                    "entity_count": 5,
                    "rank": 1.0,
                    "period": "2026-03-24",
                    "modularity": 0.4,
                },
                {
                    "id": "c2",
                    "title": "C2",
                    "level": 0,
                    "parent_id": None,
                    "entity_count": 3,
                    "rank": 2.0,
                    "period": "2026-03-24",
                    "modularity": 0.5,
                },
            ]
        )
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_list_communities_returns_list(self, repo):
        """Test that list_communities returns list of Community instances."""
        result = await repo.list_communities()

        assert len(result) == 2
        assert all(isinstance(c, Community) for c in result)

    @pytest.mark.asyncio
    async def test_list_communities_with_level_filter(self, repo):
        """Test that list_communities filters by level."""
        await repo.list_communities(level=0)

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]

        assert params["level"] == 0


class TestNeo4jCommunityRepoCountCommunities:
    """Test count_communities method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"total": 25}])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_count_communities_returns_total(self, repo):
        """Test that count_communities returns total count."""
        result = await repo.count_communities()
        assert result == 25

    @pytest.mark.asyncio
    async def test_count_communities_with_level_filter(self, repo):
        """Test that count_communities filters by level."""
        await repo.count_communities(level=0)

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]

        assert params["level"] == 0


class TestNeo4jCommunityRepoCreateReport:
    """Test create_report method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"id": "report-id"}])
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_create_report_returns_id(self, repo):
        """Test that create_report returns report ID."""
        result = await repo.create_report(
            community_id="community-id",
            title="Test Report",
            summary="Test summary",
            full_content="Full content here",
            key_entities=["E1", "E2"],
            key_relationships=["R1"],
            rank=8.5,
        )
        assert result == "report-id"

    @pytest.mark.asyncio
    async def test_create_report_raises_on_failure(self, repo):
        """Test that create_report raises when query fails."""
        repo._pool.execute_query = AsyncMock(return_value=None)

        with pytest.raises(RuntimeError, match="Failed to create community report"):
            await repo.create_report(
                community_id="non-existent",
                title="Test",
                summary="Test",
                full_content="Test",
                key_entities=[],
                key_relationships=[],
            )


class TestNeo4jCommunityRepoFindSimilarReports:
    """Test find_similar_reports method for vector similarity search."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "id": "r1",
                    "community_id": "c1",
                    "title": "Report 1",
                    "summary": "Summary 1",
                    "full_content": "Content 1",
                    "key_entities": ["E1"],
                    "key_relationships": ["R1"],
                    "rank": 5.0,
                    "score": 0.95,
                },
                {
                    "id": "r2",
                    "community_id": "c2",
                    "title": "Report 2",
                    "summary": "Summary 2",
                    "full_content": "Content 2",
                    "key_entities": ["E2"],
                    "key_relationships": ["R2"],
                    "rank": 6.0,
                    "score": 0.85,
                },
            ]
        )
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_find_similar_reports_returns_tuples(self, repo):
        """Test that find_similar_reports returns (report, score) tuples."""
        query_embedding = [0.1] * 1536
        result = await repo.find_similar_reports(query_embedding, top_k=5)

        assert len(result) == 2
        assert all(isinstance(r[0], CommunityReport) for r in result)
        assert all(isinstance(r[1], float) for r in result)

    @pytest.mark.asyncio
    async def test_find_similar_reports_with_level_filter(self, repo):
        """Test that find_similar_reports filters by level."""
        query_embedding = [0.1] * 1536
        await repo.find_similar_reports(query_embedding, top_k=5, level=0)

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]

        assert params["level"] == 0


class TestNeo4jCommunityRepoGetCommunityMetrics:
    """Test get_community_metrics method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(
            return_value=[
                {
                    "total_communities": 25,
                    "levels": 3,
                    "avg_size": 33.2,
                    "max_size": 120,
                    "min_size": 5,
                    "leaf_count": 20,
                    "reports": 22,
                    "orphan_communities": 2,
                }
            ]
        )
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_get_community_metrics_returns_dict(self, repo):
        """Test that get_community_metrics returns metrics dict."""
        result = await repo.get_community_metrics()

        assert result["total_communities"] == 25
        assert result["levels"] == 3
        assert result["avg_size"] == 33.2
        assert result["reports"] == 22

    @pytest.mark.asyncio
    async def test_get_community_metrics_returns_empty_on_no_data(self, repo):
        """Test that get_community_metrics returns empty dict when no data."""
        repo._pool.execute_query = AsyncMock(return_value=None)
        result = await repo.get_community_metrics()

        assert result["total_communities"] == 0
        assert result["levels"] == 0


class TestNeo4jCommunityRepoGetLevelDistribution:
    """Test get_level_distribution method."""

    @pytest.fixture
    def repo(self):
        """Create Neo4jCommunityRepo instance with mocked pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(
            return_value=[
                {"level": 0, "count": 20},
                {"level": 1, "count": 4},
                {"level": 2, "count": 1},
            ]
        )
        return Neo4jCommunityRepo(pool)

    @pytest.mark.asyncio
    async def test_get_level_distribution_returns_list(self, repo):
        """Test that get_level_distribution returns list of level counts."""
        result = await repo.get_level_distribution()

        assert len(result) == 3
        assert result[0]["level"] == 0
        assert result[0]["count"] == 20
        assert result[2]["level"] == 2
        assert result[2]["count"] == 1
