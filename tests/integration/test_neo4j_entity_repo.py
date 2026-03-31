# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Neo4jEntityRepo - uses real Neo4j database."""

import pytest

from modules.storage.neo4j.entity_repo import Neo4jEntityRepo


class TestNeo4jEntityRepoIntegration:
    """Integration tests for Neo4jEntityRepo with real Neo4j."""

    @pytest.fixture
    def entity_repo(self, neo4j_pool):
        """Create Neo4jEntityRepo instance with real pool."""
        return Neo4jEntityRepo(neo4j_pool)

    def test_entity_repo_initialization(self, entity_repo, neo4j_pool):
        """Test Neo4jEntityRepo initializes correctly."""
        assert entity_repo._pool is neo4j_pool

    def test_max_merge_retries_constant(self, entity_repo):
        """Test MAX_MERGE_RETRIES is defined."""
        assert entity_repo.MAX_MERGE_RETRIES == 3

    @pytest.mark.asyncio
    async def test_ensure_constraints(self, entity_repo):
        """Test ensure_constraints creates constraints."""
        await entity_repo.ensure_constraints()

    @pytest.mark.asyncio
    async def test_merge_entity_creates_new(self, entity_repo, unique_id):
        """Test merge_entity creates new entity."""
        entity_name = f"TestEntity_{unique_id}"

        try:
            result = await entity_repo.merge_entity(
                canonical_name=entity_name,
                entity_type="人物",
                description="Test entity for integration",
            )

            assert result is not None
            # Neo4j element ID format: "dbid:elementid" (e.g., "4:abc123:5")
            assert isinstance(result, str)
        finally:
            # Cleanup
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_find_entity_found(self, entity_repo, unique_id):
        """Test find_entity returns entity when found."""
        entity_name = f"TestEntity_Find_{unique_id}"

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
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_find_entity_not_found(self, entity_repo, unique_id):
        """Test find_entity returns None when not found."""
        result = await entity_repo.find_entity(f"NonExistent_{unique_id}", "人物")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_entity_by_id_found(self, entity_repo, unique_id):
        """Test find_entity_by_id returns entity."""
        entity_name = f"TestEntity_ByID_{unique_id}"

        # First create entity
        neo4j_id = await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            result = await entity_repo.find_entity_by_id(neo4j_id)

            assert result is not None
            assert result["neo4j_id"] == neo4j_id
            assert result["canonical_name"] == entity_name
        finally:
            # Cleanup
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_find_entity_by_id_not_found(self, entity_repo):
        """Test find_entity_by_id returns None when not found."""
        result = await entity_repo.find_entity_by_id("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_add_alias_success(self, entity_repo, unique_id):
        """Test add_alias adds alias to entity."""
        entity_name = f"TestEntity_Alias_{unique_id}"

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

            # Verify alias was added
            entity = await entity_repo.find_entity(entity_name, "人物")
            assert "TestAlias" in entity["aliases"]
        finally:
            # Cleanup
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_add_alias_entity_not_found(self, entity_repo, unique_id):
        """Test add_alias returns False when entity not found."""
        result = await entity_repo.add_alias(
            canonical_name=f"NonExistent_{unique_id}",
            entity_type="人物",
            alias="TestAlias",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_merge_relation(self, entity_repo, unique_id):
        """Test merge_relation creates relationship."""
        entity1_name = f"TestEntity_Rel1_{unique_id}"
        entity2_name = f"TestEntity_Rel2_{unique_id}"

        # Create two entities
        neo4j_id1 = await entity_repo.merge_entity(
            canonical_name=entity1_name,
            entity_type="人物",
        )
        neo4j_id2 = await entity_repo.merge_entity(
            canonical_name=entity2_name,
            entity_type="人物",
        )

        try:
            await entity_repo.merge_relation(
                from_neo4j_id=neo4j_id1,
                to_neo4j_id=neo4j_id2,
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
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity) WHERE e.canonical_name IN [$name1, $name2] DETACH DELETE e",
                {"name1": entity1_name, "name2": entity2_name},
            )

    @pytest.mark.asyncio
    async def test_get_entity_relations(self, entity_repo, unique_id):
        """Test get_entity_relations returns relations."""
        entity1_name = f"TestEntity_GetRel1_{unique_id}"
        entity2_name = f"TestEntity_GetRel2_{unique_id}"

        # Create entities and relation
        neo4j_id1 = await entity_repo.merge_entity(
            canonical_name=entity1_name,
            entity_type="人物",
        )
        neo4j_id2 = await entity_repo.merge_entity(
            canonical_name=entity2_name,
            entity_type="人物",
        )
        await entity_repo.merge_relation(
            from_neo4j_id=neo4j_id1,
            to_neo4j_id=neo4j_id2,
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
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity) WHERE e.canonical_name IN [$name1, $name2] DETACH DELETE e",
                {"name1": entity1_name, "name2": entity2_name},
            )

    @pytest.mark.asyncio
    async def test_list_all_entity_ids(self, entity_repo, unique_id):
        """Test list_all_entity_ids returns all IDs."""
        entity_name = f"TestEntity_List_{unique_id}"

        # Create entity
        neo4j_id = await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            result = await entity_repo.list_all_entity_ids()

            assert isinstance(result, set)
            assert neo4j_id in result
        finally:
            # Cleanup
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_delete_orphan_entities(self, entity_repo, unique_id):
        """Test delete_orphan_entities removes orphans."""
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
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )

    @pytest.mark.asyncio
    async def test_merge_mentions_relation_with_role(self, entity_repo, unique_id):
        """Test merge_mentions_relation creates MENTIONS with role."""
        entity_name = f"TestEntity_Mention_{unique_id}"

        # Create entity
        neo4j_id = await entity_repo.merge_entity(
            canonical_name=entity_name,
            entity_type="人物",
        )

        try:
            await entity_repo.merge_mentions_relation(
                article_neo4j_id="test-article-neo4j-id",
                entity_neo4j_id=neo4j_id,
                role="subject",
            )
        finally:
            # Cleanup
            await entity_repo._pool.execute_query(
                "MATCH (e:Entity {canonical_name: $name}) DETACH DELETE e",
                {"name": entity_name},
            )
