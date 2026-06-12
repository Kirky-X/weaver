# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4jEntityRepo."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from neo4j.exceptions import ConstraintError

from modules.storage.neo4j.entity_repo import Neo4jEntityRepo


class TestNeo4jEntityRepo:
    """Tests for Neo4jEntityRepo."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create Neo4jEntityRepo instance."""
        return Neo4jEntityRepo(mock_pool)

    def test_init(self, mock_pool):
        """Test initialization."""
        repo = Neo4jEntityRepo(mock_pool)
        assert repo._pool is mock_pool

    def test_max_merge_retries(self):
        """Test MAX_MERGE_RETRIES constant."""
        assert Neo4jEntityRepo.MAX_MERGE_RETRIES == 3

    def test_default_batch_size(self):
        """Test DEFAULT_BATCH_SIZE constant."""
        assert Neo4jEntityRepo.DEFAULT_BATCH_SIZE == 1000

    @pytest.mark.asyncio
    async def test_ensure_constraints(self, repo, mock_pool):
        """Test ensure_constraints creates constraints."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        await repo.ensure_constraints()

        assert mock_pool.execute_query.call_count >= 1

    @pytest.mark.asyncio
    async def test_ensure_constraints_already_exists(self, repo, mock_pool):
        """Test ensure_constraints handles existing constraint."""
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Constraint already exists"))

        # Should not raise
        await repo.ensure_constraints()

    @pytest.mark.asyncio
    async def test_merge_entity_create_new(self, repo, mock_pool):
        """Test merge_entity creates new entity."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # find_entity returns None
                [{"neo4j_id": "neo4j_123"}],  # MERGE result
            ]
        )

        result = await repo.merge_entity(
            canonical_name="张三",
            entity_type="人物",
            description="测试描述",
            tier=2,
        )

        assert result == "neo4j_123"

    @pytest.mark.asyncio
    async def test_merge_entity_update_tier_1(self, repo, mock_pool):
        """Test merge_entity updates with tier 1 (authoritative)."""
        existing_entity = {
            "neo4j_id": "neo4j_123",
            "canonical_name": "张三",
            "type": "人物",
            "tier": 2,
        }

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [existing_entity],  # find_entity returns existing
                [{"neo4j_id": "neo4j_123"}],  # Update result
            ]
        )

        result = await repo.merge_entity(
            canonical_name="张三",
            entity_type="人物",
            tier=1,  # More authoritative than existing tier 2
        )

        assert result == "neo4j_123"

    @pytest.mark.asyncio
    async def test_merge_entity_add_alias(self, repo, mock_pool):
        """Test merge_entity adds alias for same/lower tier."""
        existing_entity = {
            "neo4j_id": "neo4j_123",
            "canonical_name": "张三",
            "type": "人物",
            "tier": 1,
        }

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [existing_entity],  # find_entity returns existing
                [{"neo4j_id": "neo4j_123"}],  # Update result
            ]
        )

        result = await repo.merge_entity(
            canonical_name="张三",
            entity_type="人物",
            tier=2,  # Same or lower tier
        )

        assert result == "neo4j_123"

    @pytest.mark.asyncio
    async def test_merge_entity_constraint_error_retry(self, repo, mock_pool):
        """Test merge_entity retries on ConstraintError."""
        existing_entity = {
            "neo4j_id": "neo4j_123",
            "canonical_name": "张三",
            "type": "人物",
        }

        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # First find_entity
                ConstraintError("Constraint violation"),  # First MERGE fails
                [existing_entity],  # Second find_entity
                [{"neo4j_id": "neo4j_123"}],  # Retry succeeds
            ]
        )

        with patch.object(repo, "_sleep", AsyncMock()):
            result = await repo.merge_entity(
                canonical_name="张三",
                entity_type="人物",
            )

        assert result == "neo4j_123"

    @pytest.mark.asyncio
    async def test_merge_entity_constraint_error_max_retries(self, repo, mock_pool):
        """Test merge_entity raises after max retries."""
        mock_pool.execute_query = AsyncMock(
            side_effect=[
                [],  # find_entity
                ConstraintError("Constraint violation"),
                [],  # find_entity after failure
                [],  # find_entity
                ConstraintError("Constraint violation"),
                [],  # find_entity after failure
                [],  # find_entity
                ConstraintError("Constraint violation"),
                [],  # find_entity after failure
            ]
        )

        with patch.object(repo, "_sleep", AsyncMock()):
            with pytest.raises(ConstraintError):
                await repo.merge_entity(
                    canonical_name="张三",
                    entity_type="人物",
                )

    @pytest.mark.asyncio
    async def test_find_entity_found(self, repo, mock_pool):
        """Test find_entity returns entity when found."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo4j_123",
                    "id": "uuid-123",
                    "canonical_name": "张三",
                    "type": "人物",
                    "aliases": ["张三", "老张"],
                    "description": "测试实体",
                }
            ]
        )

        result = await repo.find_entity("张三", "人物")

        assert result is not None
        assert result["canonical_name"] == "张三"

    @pytest.mark.asyncio
    async def test_find_entity_not_found(self, repo, mock_pool):
        """Test find_entity returns None when not found."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.find_entity("不存在", "人物")

        assert result is None

    @pytest.mark.asyncio
    async def test_find_entity_by_id_found(self, repo, mock_pool):
        """Test find_entity_by_id returns entity when found."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "neo4j_123",
                    "id": "uuid-123",
                    "canonical_name": "张三",
                    "type": "人物",
                }
            ]
        )

        result = await repo.find_entity_by_id("neo4j_123")

        assert result is not None
        assert result["neo4j_id"] == "neo4j_123"

    @pytest.mark.asyncio
    async def test_find_entity_by_id_not_found(self, repo, mock_pool):
        """Test find_entity_by_id returns None when not found."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.find_entity_by_id("nonexistent_id")

        assert result is None

    @pytest.mark.asyncio
    async def test_add_alias(self, repo, mock_pool):
        """Test add_alias adds alias to entity."""
        mock_pool.execute_query = AsyncMock(return_value=[{"aliases": ["张三", "老张"]}])

        result = await repo.add_alias("张三", "人物", "老张")

        assert result is True

    @pytest.mark.asyncio
    async def test_add_alias_entity_not_found(self, repo, mock_pool):
        """Test add_alias returns False when entity not found."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.add_alias("不存在", "人物", "别名")

        assert result is False

    @pytest.mark.asyncio
    async def test_merge_relation_dynamic_type(self, repo, mock_pool):
        """Test merge_relation with dynamic edge type."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        await repo.merge_relation(
            from_entity_id="id1",
            to_entity_id="id2",
            edge_type="PARTNERS_WITH",
            properties={"raw_type": "合作", "direction": "bidirectional"},
        )

        mock_pool.execute_query.assert_called_once()
        call_args = mock_pool.execute_query.call_args
        query = call_args[0][0]
        assert "PARTNERS_WITH" in query
        assert "ON CREATE SET" in query
        assert "ON MATCH SET" in query
        params = call_args[0][1]
        assert params["props"]["raw_type"] == "合作"
        assert params["props"]["direction"] == "bidirectional"

    @pytest.mark.asyncio
    async def test_merge_relation_invalid_type(self, repo, mock_pool):
        """Test merge_relation rejects invalid edge type."""
        with pytest.raises(ValueError, match="Invalid edge type"):
            await repo.merge_relation(
                from_entity_id="id1",
                to_entity_id="id2",
                edge_type="invalid-type!",
            )

        mock_pool.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_merge_relation_with_no_properties(self, repo, mock_pool):
        """Test merge_relation with no properties passes empty dict."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        await repo.merge_relation(
            from_entity_id="id1",
            to_entity_id="id2",
            edge_type="REGULATES",
        )

        call_args = mock_pool.execute_query.call_args
        params = call_args[0][1]
        assert params["props"] == {}

    @pytest.mark.asyncio
    async def test_get_entity_relations(self, repo, mock_pool):
        """Test get_entity_relations returns relations."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {
                    "from_id": "id1",
                    "relation_type": "RELATED_TO",
                    "relation_props": {},
                    "to_id": "id2",
                    "to_name": "实体2",
                    "to_type": "组织机构",
                }
            ]
        )

        result = await repo.get_entity_relations("张三", "人物")

        assert len(result) == 1
        assert result[0]["relation_type"] == "RELATED_TO"

    @pytest.mark.asyncio
    async def test_get_entity_relations_with_limit(self, repo, mock_pool):
        """Test get_entity_relations respects limit."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        await repo.get_entity_relations("张三", "人物", limit=10)

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_all_entity_ids(self, repo, mock_pool):
        """Test list_all_entity_ids returns set of IDs."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"neo4j_id": "id1"},
                {"neo4j_id": "id2"},
            ]
        )

        result = await repo.list_all_entity_ids()

        assert result == {"id1", "id2"}

    @pytest.mark.asyncio
    async def test_list_all_entity_ids_empty(self, repo, mock_pool):
        """Test list_all_entity_ids returns empty set."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.list_all_entity_ids()

        assert result == set()

    @pytest.mark.asyncio
    async def test_delete_orphan_entities(self, repo, mock_pool):
        """Test delete_orphan_entities executes delete query."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        result = await repo.delete_orphan_entities()

        mock_pool.execute_query.assert_called_once()
        assert result == 0  # Returns 0 as count not easily available

    @pytest.mark.asyncio
    async def test_merge_mentions_relation(self, repo, mock_pool):
        """Test merge_mentions_relation creates MENTIONS relationship."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        await repo.merge_mentions_relation(
            article_id="article_id",
            entity_id="entity_id",
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_mentions_relation_with_role(self, repo, mock_pool):
        """Test merge_mentions_relation creates relationship with role."""
        mock_pool.execute_query = AsyncMock(return_value=[])

        await repo.merge_mentions_relation(
            article_id="article_id",
            entity_id="entity_id",
            role="subject",
        )

        mock_pool.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_sleep(self):
        """Test _sleep helper method."""
        import asyncio

        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            await Neo4jEntityRepo._sleep(0.1)
            mock_sleep.assert_called_once_with(0.1)

    @pytest.mark.asyncio
    async def test_merge_entities_batch_empty(self, repo):
        """Test merge_entities_batch returns empty for empty input."""
        result = await repo.merge_entities_batch([])

        assert result == {"created": 0, "updated": 0}

    @pytest.mark.asyncio
    async def test_merge_entities_batch(self, repo, mock_pool):
        """Test merge_entities_batch creates entities."""
        mock_pool.execute_query = AsyncMock(return_value=[{"created": 2, "updated": 1}])

        entities = [
            {"canonical_name": "实体1", "type": "人物", "description": "描述1"},
            {"canonical_name": "实体2", "type": "组织机构", "description": "描述2"},
            {"canonical_name": "实体3", "type": "地点", "description": "描述3"},
        ]

        result = await repo.merge_entities_batch(entities)

        assert result["created"] == 2
        assert result["updated"] == 1

    @pytest.mark.asyncio
    async def test_merge_entities_batch_with_custom_size(self, repo, mock_pool):
        """Test merge_entities_batch with custom batch size."""
        mock_pool.execute_query = AsyncMock(return_value=[{"created": 5, "updated": 0}])

        entities = [
            {"canonical_name": f"实体{i}", "type": "人物", "description": f"描述{i}"}
            for i in range(5)
        ]

        result = await repo.merge_entities_batch(entities, batch_size=2)

        # With 5 entities and batch_size=2, there should be 3 batches (2+2+1)
        # Each batch mock returns created=5, so total is 5 * 3 = 15
        assert result["created"] == 15

    @pytest.mark.asyncio
    async def test_add_aliases_batch_empty(self, repo):
        """Test add_aliases_batch returns 0 for empty input."""
        result = await repo.add_aliases_batch([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_add_aliases_batch(self, repo, mock_pool):
        """Test add_aliases_batch adds aliases."""
        mock_pool.execute_query = AsyncMock(return_value=[{"updated": 3}])

        aliases = [
            {"canonical_name": "张三", "type": "人物", "alias": "老张"},
            {"canonical_name": "李四", "type": "人物", "alias": "老李"},
        ]

        result = await repo.add_aliases_batch(aliases)

        assert result == 3

    @pytest.mark.asyncio
    async def test_merge_relations_batch_empty(self, repo):
        """Test merge_relations_batch returns 0 for empty input."""
        result = await repo.merge_relations_batch([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_merge_relations_batch_dynamic_types(self, repo, mock_pool):
        """Test merge_relations_batch groups by edge_type."""
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 2}])

        relations = [
            {
                "from_name": "张三",
                "from_type": "人物",
                "to_name": "公司A",
                "to_type": "组织机构",
                "edge_type": "PARTNERS_WITH",
                "properties": {"raw_type": "合作"},
            },
            {
                "from_name": "李四",
                "from_type": "人物",
                "to_name": "公司B",
                "to_type": "组织机构",
                "edge_type": "PARTNERS_WITH",
                "properties": {"raw_type": "合作"},
            },
            {
                "from_name": "王五",
                "from_type": "人物",
                "to_name": "机构C",
                "to_type": "组织机构",
                "edge_type": "REGULATES",
                "properties": {"raw_type": "监管"},
            },
        ]

        result = await repo.merge_relations_batch(relations)

        assert result == 4  # 2 + 2 per batch group
        # Two groups = two execute_query calls
        assert mock_pool.execute_query.call_count == 2

        # Verify each query contains the correct edge type
        calls = mock_pool.execute_query.call_args_list
        queries = [c[0][0] for c in calls]
        edge_types_in_queries = []
        for q in queries:
            if "PARTNERS_WITH" in q:
                edge_types_in_queries.append("PARTNERS_WITH")
            elif "REGULATES" in q:
                edge_types_in_queries.append("REGULATES")
        assert set(edge_types_in_queries) == {"PARTNERS_WITH", "REGULATES"}

    @pytest.mark.asyncio
    async def test_merge_relations_batch_invalid_type_skipped(self, repo, mock_pool):
        """Test merge_relations_batch skips invalid edge types."""
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 1}])

        relations = [
            {
                "from_name": "张三",
                "from_type": "人物",
                "to_name": "公司A",
                "to_type": "组织机构",
                "edge_type": "invalid-type!",
                "properties": {},
            },
            {
                "from_name": "李四",
                "from_type": "人物",
                "to_name": "公司B",
                "to_type": "组织机构",
                "edge_type": "PARTNERS_WITH",
                "properties": {},
            },
        ]

        result = await repo.merge_relations_batch(relations)

        # Only the valid type group should execute
        assert result == 1
        assert mock_pool.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_merge_mentions_batch_empty(self, repo):
        """Test merge_mentions_batch returns 0 for empty input."""
        result = await repo.merge_mentions_batch([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_merge_mentions_batch(self, repo, mock_pool):
        """Test merge_mentions_batch creates MENTIONS relationships."""
        mock_pool.execute_query = AsyncMock(return_value=[{"total": 2}])

        mentions = [
            {"article_id": "article1", "entity_name": "张三", "entity_type": "人物"},
            {
                "article_id": "article1",
                "entity_name": "李四",
                "entity_type": "人物",
                "role": "subject",
            },
        ]

        result = await repo.merge_mentions_batch(mentions)

        assert result == 2

    @pytest.mark.asyncio
    async def test_find_entities_batch_empty(self, repo):
        """Test find_entities_batch returns empty list for empty input."""
        result = await repo.find_entities_batch([], "人物")

        assert result == []

    @pytest.mark.asyncio
    async def test_find_entities_batch(self, repo, mock_pool):
        """Test find_entities_batch returns entities."""
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"neo4j_id": "id1", "canonical_name": "张三", "type": "人物"},
                {"neo4j_id": "id2", "canonical_name": "李四", "type": "人物"},
            ]
        )

        result = await repo.find_entities_batch(["张三", "李四"], "人物")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_delete_entities_batch_empty(self, repo):
        """Test delete_entities_batch returns 0 for empty input."""
        result = await repo.delete_entities_batch([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_delete_entities_batch(self, repo, mock_pool):
        """Test delete_entities_batch deletes entities."""
        mock_pool.execute_query = AsyncMock(return_value=[{"deleted": 3}])

        result = await repo.delete_entities_batch(["id1", "id2", "id3"])

        assert result == 3

    def test_chunk(self):
        """Test _chunk helper method."""
        items = [1, 2, 3, 4, 5, 6, 7]
        chunks = list(Neo4jEntityRepo._chunk(items, 3))

        assert len(chunks) == 3
        assert chunks[0] == [1, 2, 3]
        assert chunks[1] == [4, 5, 6]
        assert chunks[2] == [7]

    def test_chunk_empty(self):
        """Test _chunk with empty list."""
        chunks = list(Neo4jEntityRepo._chunk([], 10))

        assert len(chunks) == 0

    def test_chunk_size_larger_than_list(self):
        """Test _chunk when size is larger than list."""
        items = [1, 2, 3]
        chunks = list(Neo4jEntityRepo._chunk(items, 10))

        assert len(chunks) == 1
        assert chunks[0] == [1, 2, 3]


class TestGetRelationTypes:
    """Tests for get_relation_types (Layer 1)."""

    @pytest.fixture
    def repo(self):
        """Create repo with mock pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return Neo4jEntityRepo(pool)

    @pytest.mark.asyncio
    async def test_get_relation_types(self, repo):
        """Test get_relation_types returns aggregated types."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "relation_type": "PARTNERS_WITH",
                    "target_count": 5,
                    "primary_direction": "outgoing",
                },
                {
                    "relation_type": "REGULATES",
                    "target_count": 3,
                    "primary_direction": "outgoing",
                },
            ]
        )

        result = await repo.get_relation_types("张三", "人物")

        assert len(result) == 2
        assert result[0]["relation_type"] == "PARTNERS_WITH"
        assert result[0]["target_count"] == 5
        assert result[1]["relation_type"] == "REGULATES"
        assert result[1]["target_count"] == 3

    @pytest.mark.asyncio
    async def test_get_relation_types_empty(self, repo):
        """Test get_relation_types returns empty for entity with no relations."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        result = await repo.get_relation_types("孤立体", "人物")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_relation_types_query_params(self, repo):
        """Test get_relation_types passes correct params."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        await repo.get_relation_types("张三", "人物")

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]
        assert params["name"] == "张三"
        assert params["type"] == "人物"


class TestFindByRelationTypes:
    """Tests for find_by_relation_types (Layer 2)."""

    @pytest.fixture
    def repo(self):
        """Create repo with mock pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return Neo4jEntityRepo(pool)

    @pytest.mark.asyncio
    async def test_find_by_relation_types_specific(self, repo):
        """Test find_by_relation_types with specific types."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "relation_type": "PARTNERS_WITH",
                    "direction": "outgoing",
                    "target_name": "公司A",
                    "target_type": "组织机构",
                    "target_description": "描述",
                    "weight": 1.2,
                },
            ]
        )

        result = await repo.find_by_relation_types(
            "张三",
            "人物",
            relation_types=["PARTNERS_WITH"],
        )

        assert len(result) == 1
        assert result[0]["target_name"] == "公司A"
        assert result[0]["relation_type"] == "PARTNERS_WITH"
        assert result[0]["weight"] == 1.2

    @pytest.mark.asyncio
    async def test_find_by_relation_types_all(self, repo):
        """Test find_by_relation_types returns all when no types specified."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "relation_type": "PARTNERS_WITH",
                    "direction": "outgoing",
                    "target_name": "公司A",
                    "target_type": "组织机构",
                    "target_description": None,
                    "weight": 1.0,
                },
                {
                    "relation_type": "REGULATES",
                    "direction": "incoming",
                    "target_name": "监管机构",
                    "target_type": "组织机构",
                    "target_description": None,
                    "weight": 0.9,
                },
            ]
        )

        result = await repo.find_by_relation_types("张三", "人物")

        assert len(result) == 2
        call_args = repo._pool.execute_query.call_args
        query = call_args[0][0]
        # Should NOT contain type-specific filters
        assert "type(r) = " not in query

    @pytest.mark.asyncio
    async def test_find_by_relation_types_invalid_type(self, repo):
        """Test find_by_relation_types rejects invalid type."""
        with pytest.raises(ValueError, match="Invalid relation type"):
            await repo.find_by_relation_types(
                "张三",
                "人物",
                relation_types=["INVALID!TYPE"],
            )

    @pytest.mark.asyncio
    async def test_find_by_relation_types_limit(self, repo):
        """Test find_by_relation_types respects limit."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        await repo.find_by_relation_types("张三", "人物", limit=10)

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]
        assert params["limit"] == 10

    @pytest.mark.asyncio
    async def test_find_by_relation_types_empty(self, repo):
        """Test find_by_relation_types returns empty when no matches."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        result = await repo.find_by_relation_types(
            "张三",
            "人物",
            relation_types=["NONEXISTENT_TYPE"],
        )

        assert result == []


class TestFindEntitiesByIds:
    """Tests for find_entities_by_ids."""

    @pytest.fixture
    def repo(self):
        """Create repo with mock pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return Neo4jEntityRepo(pool)

    @pytest.mark.asyncio
    async def test_find_entities_by_ids_found(self, repo):
        """Test find_entities_by_ids returns entities when found."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {"neo4j_id": "id1", "canonical_name": "张三", "type": "人物"},
                {"neo4j_id": "id2", "canonical_name": "李四", "type": "人物"},
            ]
        )

        result = await repo.find_entities_by_ids(["id1", "id2"])

        assert len(result) == 2
        assert result[0]["neo4j_id"] == "id1"
        assert result[1]["canonical_name"] == "李四"

    @pytest.mark.asyncio
    async def test_find_entities_by_ids_empty(self, repo):
        """Test find_entities_by_ids returns empty list when none found."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        result = await repo.find_entities_by_ids(["nonexistent_id"])

        assert result == []

    @pytest.mark.asyncio
    async def test_find_entities_by_ids_query_params(self, repo):
        """Test find_entities_by_ids passes correct params."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        await repo.find_entities_by_ids(["id1", "id2"])

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]
        assert "ids" in params
        assert params["ids"] == ["id1", "id2"]


class TestCountOrphanEntities:
    """Tests for count_orphan_entities."""

    @pytest.fixture
    def repo(self):
        """Create repo with mock pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return Neo4jEntityRepo(pool)

    @pytest.mark.asyncio
    async def test_count_orphan_entities(self, repo):
        """Test count_orphan_entities returns count."""
        repo._pool.execute_query = AsyncMock(return_value=[{"orphan_count": 5}])

        result = await repo.count_orphan_entities()

        assert result == 5

    @pytest.mark.asyncio
    async def test_count_orphan_entities_zero(self, repo):
        """Test count_orphan_entities returns 0 when no orphans."""
        repo._pool.execute_query = AsyncMock(return_value=[{"orphan_count": 0}])

        result = await repo.count_orphan_entities()

        assert result == 0


class TestFindEntitiesByKeys:
    """Tests for find_entities_by_keys."""

    @pytest.fixture
    def repo(self):
        """Create repo with mock pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return Neo4jEntityRepo(pool)

    @pytest.mark.asyncio
    async def test_find_entities_by_keys_found(self, repo):
        """Test find_entities_by_keys returns entities when found."""
        repo._pool.execute_query = AsyncMock(
            return_value=[
                {
                    "neo4j_id": "id1",
                    "canonical_name": "张三",
                    "type": "人物",
                    "aliases": ["张三", "老张"],
                    "description": "描述",
                },
                {
                    "neo4j_id": "id2",
                    "canonical_name": "公司A",
                    "type": "组织机构",
                    "aliases": ["公司A"],
                    "description": None,
                },
            ]
        )

        keys = [
            {"canonical_name": "张三", "type": "人物"},
            {"canonical_name": "公司A", "type": "组织机构"},
        ]
        result = await repo.find_entities_by_keys(keys)

        assert len(result) == 2
        assert result[0]["canonical_name"] == "张三"
        assert result[1]["type"] == "组织机构"

    @pytest.mark.asyncio
    async def test_find_entities_by_keys_empty(self, repo):
        """Test find_entities_by_keys returns empty list for empty input."""
        result = await repo.find_entities_by_keys([])

        assert result == []

    @pytest.mark.asyncio
    async def test_find_entities_by_keys_partial_match(self, repo):
        """Test find_entities_by_keys returns only found entities."""
        repo._pool.execute_query = AsyncMock(
            return_value=[{"neo4j_id": "id1", "canonical_name": "张三", "type": "人物"}]
        )

        keys = [
            {"canonical_name": "张三", "type": "人物"},
            {"canonical_name": "不存在", "type": "人物"},
        ]
        result = await repo.find_entities_by_keys(keys)

        assert len(result) == 1
        assert result[0]["canonical_name"] == "张三"

    @pytest.mark.asyncio
    async def test_find_entities_by_keys_query_params(self, repo):
        """Test find_entities_by_keys passes correct params."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        keys = [
            {"canonical_name": "张三", "type": "人物"},
            {"canonical_name": "公司A", "type": "组织机构"},
        ]
        await repo.find_entities_by_keys(keys)

        call_args = repo._pool.execute_query.call_args
        params = call_args[0][1]
        assert "keys" in params
        assert len(params["keys"]) == 2
        assert params["keys"][0]["canonical_name"] == "张三"


class TestGetEntityNeighborhood:
    """Tests for get_entity_neighborhood."""

    @pytest.fixture
    def repo(self):
        """Create repo with mock pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock()
        return Neo4jEntityRepo(pool)

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_found(self, repo):
        """Test get_entity_neighborhood returns neighborhood data."""
        # Mock find_entity
        repo._pool.execute_query = AsyncMock(
            side_effect=[
                # find_entity
                [{"neo4j_id": "id1", "canonical_name": "张三", "type": "人物"}],
                # events query
                [
                    {
                        "id": "event1",
                        "content": "事件内容",
                        "timestamp": "2024-01-01",
                        "source": "http://example.com",
                    }
                ],
                # related entities query (hops=2)
                [{"name": "公司A", "type": "组织机构"}],
                # relations query
                [
                    {
                        "type": "WORKS_FOR",
                        "source": "张三",
                        "target": "公司A",
                        "confidence": 0.9,
                    }
                ],
            ]
        )

        result = await repo.get_entity_neighborhood("张三", hops=2, limit=10)

        assert result is not None
        assert result["center"] == "张三"
        assert len(result["events"]) == 1
        assert len(result["related_entities"]) == 1
        assert len(result["relations"]) == 1
        assert result["hops"] == 2

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_not_found(self, repo):
        """Test get_entity_neighborhood returns None when entity not found."""
        repo._pool.execute_query = AsyncMock(return_value=[])

        result = await repo.get_entity_neighborhood("不存在")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_hops_1(self, repo):
        """Test get_entity_neighborhood with hops=1."""
        repo._pool.execute_query = AsyncMock(
            side_effect=[
                [{"neo4j_id": "id1", "canonical_name": "张三", "type": "人物"}],
                [],  # events
                [],  # related entities
                [],  # relations
            ]
        )

        result = await repo.get_entity_neighborhood("张三", hops=1)

        assert result is not None
        assert result["hops"] == 1
        # Verify the query used hops=1 pattern (should not contain *1..2)
        calls = repo._pool.execute_query.call_args_list
        related_query = calls[2][0][0]  # Third call is related entities
        assert "*1..2" not in related_query

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_with_type(self, repo):
        """Test get_entity_neighborhood with entity_type parameter."""
        repo._pool.execute_query = AsyncMock(
            side_effect=[
                [{"neo4j_id": "id1", "canonical_name": "张三", "type": "人物"}],
                [],  # events
                [],  # related entities
                [],  # relations
            ]
        )

        await repo.get_entity_neighborhood("张三", entity_type="人物")

        # Verify find_entity was called with the type
        first_call = repo._pool.execute_query.call_args_list[0]
        query = first_call[0][0]
        params = first_call[0][1]
        assert "canonical_name" in query
        assert params["canonical_name"] == "张三"
        assert params["type"] == "人物"
