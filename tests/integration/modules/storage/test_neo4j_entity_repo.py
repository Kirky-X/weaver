# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for EntityRepository - uses fallback graph databases.

Tests with Neo4j or LadybugDB (fallback) using the EntityRepository protocol.
"""

import pytest


class TestEntityRepositoryIntegration:
    """Integration tests for EntityRepository with fallback graph databases."""

    @pytest.fixture
    async def entity_repo(self, graph_pool):
        """Create EntityRepository instance based on graph pool type."""
        pool, db_type = graph_pool
        if db_type == "ladybug":
            from modules.storage.ladybug import LadybugEntityRepo

            return LadybugEntityRepo(pool)
        else:
            from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

            return Neo4jEntityRepo(pool)

    def test_entity_repo_initialization(self, entity_repo, graph_pool):
        """Test EntityRepository initializes correctly."""
        pool, _ = graph_pool
        assert entity_repo._pool is pool

    def test_max_merge_retries_constant(self, entity_repo):
        """Test MAX_MERGE_RETRIES is defined."""
        assert entity_repo.MAX_MERGE_RETRIES == 3

    @pytest.mark.asyncio
    async def test_ensure_constraints(self, entity_repo):
        """Test ensure_constraints creates constraints."""
        await entity_repo.ensure_constraints()

    @pytest.mark.asyncio
    async def test_merge_entity_creates_new(self, entity_repo, graph_pool, unique_id):
        """Test merge_entity creates new entity."""
        entity_name = f"TestEntity_{unique_id}"
        pool, _ = graph_pool

        try:
            result = await entity_repo.merge_entity(
                canonical_name=entity_name,
                entity_type="人物",
                description="Test entity for integration",
            )

            assert result is not None
            assert isinstance(result, str)
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_find_entity_found(self, entity_repo, graph_pool, unique_id):
        """Test find_entity returns entity when found."""
        entity_name = f"TestEntity_Find_{unique_id}"
        pool, _ = graph_pool

        # First create entity
        await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
            description="Test entity",
        )

        try:
            result = await entity_repo.find_entity(entity_name, "人物")

            assert result is not None
            assert result["canonical_name"] == entity_name
            assert result["type"] == "人物"
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_find_entity_not_found(self, entity_repo, unique_id):
        """Test find_entity returns None when not found."""
        result = await entity_repo.find_entity(f"NonExistent_{unique_id}", "人物")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_entity_by_id_found(self, entity_repo, graph_pool, unique_id):
        """Test find_entity_by_id returns entity."""
        entity_name = f"TestEntity_ByID_{unique_id}"
        pool, _ = graph_pool

        # First create entity
        entity_id = await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            result = await entity_repo.find_entity_by_id(entity_id)

            assert result is not None
            assert result["neo4j_id"] == entity_id
            assert result["canonical_name"] == entity_name
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_find_entity_by_id_not_found(self, entity_repo):
        """Test find_entity_by_id returns None when not found."""
        result = await entity_repo.find_entity_by_id("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_add_alias_success(self, entity_repo, graph_pool, unique_id):
        """Test add_alias adds alias to entity."""
        entity_name = f"TestEntity_Alias_{unique_id}"
        pool, db_type = graph_pool

        # First create entity
        await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            result = await entity_repo.add_alias(
                canonical_name=entity_name,
                entity_type="人物",
                alias="TestAlias",
            )

            assert result is True

            # Verify alias was added - only for Neo4j, LadybugDB doesn't support arrays
            if db_type == "neo4j":
                entity = await entity_repo.find_entity(entity_name, "人物")
                assert "TestAlias" in entity["aliases"]
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_add_alias_entity_not_found(self, entity_repo, graph_pool, unique_id):
        """Test add_alias returns False when entity not found."""
        pool, db_type = graph_pool

        result = await entity_repo.add_alias(
            canonical_name=f"NonExistent_{unique_id}",
            entity_type="人物",
            alias="TestAlias",
        )

        # Neo4j returns False for non-existent entity, LadybugDB always returns True
        if db_type == "neo4j":
            assert result is False
        else:
            # LadybugDB doesn't have array support, so add_alias always returns True
            assert result is True

    @pytest.mark.asyncio
    async def test_merge_relation(self, entity_repo, graph_pool, unique_id):
        """Test merge_relation creates relationship."""
        entity1_name = f"TestEntity_Rel1_{unique_id}"
        entity2_name = f"TestEntity_Rel2_{unique_id}"
        pool, _ = graph_pool

        # Create two entities
        entity_id1 = await entity_repo.merge_entity(
            canonical_name=entity1_name,
            entity_type="人物",
        )
        entity_id2 = await entity_repo.merge_entity(
            canonical_name=entity2_name,
            entity_type="人物",
        )

        try:
            await entity_repo.merge_relation(
                from_entity_id=entity_id1,
                to_entity_id=entity_id2,
                edge_type="RELATED_TO",
                properties={"weight": 0.9, "source_article_id": "test-article"},
            )

            # Verify relationship was created
            relations = await entity_repo.get_entity_relations(
                canonical_name=entity1_name,
                entity_type="人物",
                limit=10,
            )
            assert len(relations) >= 1
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity) WHERE e.canonical_name IN [$name1, $name2] DETACH DELETE e",
                {"name1": entity1_name, "name2": entity2_name},
            )

    @pytest.mark.asyncio
    async def test_get_entity_relations(self, entity_repo, graph_pool, unique_id):
        """Test get_entity_relations returns relations."""
        entity1_name = f"TestEntity_GetRel1_{unique_id}"
        entity2_name = f"TestEntity_GetRel2_{unique_id}"
        pool, _ = graph_pool

        # Create entities and relation
        entity_id1 = await entity_repo.merge_entity(
            canonical_name=entity1_name,
            entity_type="人物",
        )
        entity_id2 = await entity_repo.merge_entity(
            canonical_name=entity2_name,
            entity_type="人物",
        )
        await entity_repo.merge_relation(
            from_entity_id=entity_id1,
            to_entity_id=entity_id2,
            edge_type="RELATED_TO",
        )

        try:
            result = await entity_repo.get_entity_relations(
                canonical_name=entity1_name,
                entity_type="人物",
                limit=10,
            )

            assert isinstance(result, list)
            assert len(result) >= 1
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity) WHERE e.canonical_name IN [$name1, $name2] DETACH DELETE e",
                {"name1": entity1_name, "name2": entity2_name},
            )

    @pytest.mark.asyncio
    async def test_list_all_entity_ids(self, entity_repo, graph_pool, unique_id):
        """Test list_all_entity_ids returns all IDs."""
        entity_name = f"TestEntity_List_{unique_id}"
        pool, _ = graph_pool

        # Create entity
        entity_id = await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            result = await entity_repo.list_all_entity_ids()

            assert isinstance(result, set)
            assert entity_id in result
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_delete_orphan_entities(self, entity_repo, graph_pool, unique_id):
        """Test delete_orphan_entities removes orphans."""
        pool, _ = graph_pool
        # Create orphan entity (no relations)
        entity_name = f"TestEntity_Orphan_{unique_id}"
        await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            await entity_repo.delete_orphan_entities()

            # Verify orphan was deleted
            entity = await entity_repo.find_entity(entity_name, "人物")
            assert entity is None
        finally:
            # Extra cleanup if needed
            await pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_merge_mentions_relation_with_role(self, entity_repo, graph_pool, unique_id):
        """Test merge_mentions_relation creates MENTIONS with role."""
        entity_name = f"TestEntity_Mention_{unique_id}"
        pool, _ = graph_pool

        # Create entity
        entity_id = await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            await entity_repo.merge_mentions_relation(
                article_id="test-article-id",
                entity_id=entity_id,
                role="subject",
            )
        finally:
            # Cleanup
            await pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )
