"""Integration tests for Neo4jEntityRepo."""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from modules.storage.neo4j.entity_repo import Neo4jEntityRepo


class TestNeo4jEntityRepoIntegration:
    """Integration tests for Neo4jEntityRepo with Neo4j."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Neo4jPool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.fixture
    def entity_repo(self, mock_pool):
        """Create Neo4jEntityRepo instance."""
        return Neo4jEntityRepo(mock_pool)

    def test_entity_repo_initialization(self, entity_repo, mock_pool):
        """Test Neo4jEntityRepo initializes correctly."""
        assert entity_repo._pool is mock_pool

    def test_max_merge_retries_constant(self, entity_repo):
        """Test MAX_MERGE_RETRIES is defined."""
        assert entity_repo.MAX_MERGE_RETRIES == 3

    @pytest.mark.asyncio
    async def test_ensure_constraints(self, entity_repo, mock_pool):
        """Test ensure_constraints creates constraints."""
        mock_pool.execute_query.return_value = None

        await entity_repo.ensure_constraints()
        mock_pool.execute_query.assert_called()

    @pytest.mark.asyncio
    async def test_merge_entity_creates_new(self, entity_repo, mock_pool):
        """Test merge_entity creates new entity."""
        mock_pool.execute_query.return_value = [{"neo4j_id": "test-neo4j-id"}]

        result = await entity_repo.merge_entity(
            canonical_name="Test Entity",
            entity_type="person",
            description="Test description",
        )

        assert result == "test-neo4j-id"
        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_entity_with_retry(self, entity_repo, mock_pool):
        """Test merge_entity retries on constraint error."""
        from neo4j.exceptions import ConstraintError

        call_count = 0

        async def mock_execute(query, params):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConstraintError("Constraint violation")
            return [{"neo4j_id": "retry-neo4j-id"}]

        mock_pool.execute_query = mock_execute

        with patch.object(entity_repo, "find_entity", new_callable=AsyncMock) as mock_find:
            mock_find.return_value = None

            result = await entity_repo.merge_entity(
                canonical_name="Test Entity",
                entity_type="person",
            )

        assert result == "retry-neo4j-id"

    @pytest.mark.asyncio
    async def test_find_entity_found(self, entity_repo, mock_pool):
        """Test find_entity returns entity when found."""
        mock_pool.execute_query.return_value = [{
            "neo4j_id": "test-id",
            "id": "uuid-123",
            "canonical_name": "Test Entity",
            "type": "person",
            "aliases": ["alias1"],
            "description": "Test",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }]

        result = await entity_repo.find_entity("Test Entity", "person")

        assert result is not None
        assert result["canonical_name"] == "Test Entity"
        assert result["type"] == "person"

    @pytest.mark.asyncio
    async def test_find_entity_not_found(self, entity_repo, mock_pool):
        """Test find_entity returns None when not found."""
        mock_pool.execute_query.return_value = []

        result = await entity_repo.find_entity("Missing Entity", "person")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_entity_by_id_found(self, entity_repo, mock_pool):
        """Test find_entity_by_id returns entity."""
        mock_pool.execute_query.return_value = [{
            "neo4j_id": "test-neo4j-id",
            "id": "uuid-123",
            "canonical_name": "Test Entity",
            "type": "person",
            "aliases": [],
            "description": None,
            "created_at": None,
            "updated_at": None,
        }]

        result = await entity_repo.find_entity_by_id("test-neo4j-id")

        assert result is not None
        assert result["neo4j_id"] == "test-neo4j-id"

    @pytest.mark.asyncio
    async def test_find_entity_by_id_not_found(self, entity_repo, mock_pool):
        """Test find_entity_by_id returns None when not found."""
        mock_pool.execute_query.return_value = []

        result = await entity_repo.find_entity_by_id("missing-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_add_alias_success(self, entity_repo, mock_pool):
        """Test add_alias adds alias to entity."""
        mock_pool.execute_query.return_value = [{
            "aliases": ["Original", "New Alias"]
        }]

        result = await entity_repo.add_alias(
            canonical_name="Test Entity",
            entity_type="person",
            alias="New Alias",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_add_alias_entity_not_found(self, entity_repo, mock_pool):
        """Test add_alias returns False when entity not found."""
        mock_pool.execute_query.return_value = []

        result = await entity_repo.add_alias(
            canonical_name="Missing Entity",
            entity_type="person",
            alias="New Alias",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_merge_relation(self, entity_repo, mock_pool):
        """Test merge_relation creates relationship."""
        mock_pool.execute_query.return_value = None

        await entity_repo.merge_relation(
            from_neo4j_id="source-id",
            to_neo4j_id="target-id",
            relation_type="RELATED_TO",
            properties={"weight": 0.9, "source_article_id": "article-123"},
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_relation_without_properties(self, entity_repo, mock_pool):
        """Test merge_relation without properties."""
        mock_pool.execute_query.return_value = None

        await entity_repo.merge_relation(
            from_neo4j_id="source-id",
            to_neo4j_id="target-id",
            relation_type="RELATED_TO",
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_entity_relations(self, entity_repo, mock_pool):
        """Test get_entity_relations returns relations."""
        mock_pool.execute_query.return_value = [
            {
                "from_id": "entity-1",
                "relation_type": "RELATED_TO",
                "relation_props": {"weight": 0.9},
                "to_id": "entity-2",
                "to_name": "Related Entity",
                "to_type": "person",
            }
        ]

        result = await entity_repo.get_entity_relations(
            canonical_name="Test Entity",
            entity_type="person",
            limit=10,
        )

        assert len(result) == 1
        assert result[0]["relation_type"] == "RELATED_TO"

    @pytest.mark.asyncio
    async def test_list_all_entity_ids(self, entity_repo, mock_pool):
        """Test list_all_entity_ids returns all IDs."""
        mock_pool.execute_query.return_value = [
            {"neo4j_id": "id-1"},
            {"neo4j_id": "id-2"},
            {"neo4j_id": "id-3"},
        ]

        result = await entity_repo.list_all_entity_ids()

        assert len(result) == 3
        assert "id-1" in result
        assert "id-2" in result
        assert "id-3" in result

    @pytest.mark.asyncio
    async def test_delete_orphan_entities(self, entity_repo, mock_pool):
        """Test delete_orphan_entities removes orphans."""
        mock_pool.execute_query.return_value = None

        result = await entity_repo.delete_orphan_entities()

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_mentions_relation_with_role(self, entity_repo, mock_pool):
        """Test merge_mentions_relation creates MENTIONS with role."""
        mock_pool.execute_query.return_value = None

        await entity_repo.merge_mentions_relation(
            article_neo4j_id="article-id",
            entity_neo4j_id="entity-id",
            role="subject",
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_mentions_relation_without_role(self, entity_repo, mock_pool):
        """Test merge_mentions_relation creates MENTIONS without role."""
        mock_pool.execute_query.return_value = None

        await entity_repo.merge_mentions_relation(
            article_neo4j_id="article-id",
            entity_neo4j_id="entity-id",
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_sleep_helper(self, entity_repo):
        """Test _sleep helper method."""
        import asyncio

        start = asyncio.get_event_loop().time()
        await Neo4jEntityRepo._sleep(0.01)
        end = asyncio.get_event_loop().time()

        assert end - start >= 0.01
