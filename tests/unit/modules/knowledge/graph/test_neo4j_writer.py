# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4jWriter."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestNeo4jWriterInit:
    """Tests for Neo4jWriter initialization."""

    def test_init_with_pool(self):
        """Test Neo4jWriter initializes with pool."""
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        mock_pool = MagicMock()

        writer = Neo4jWriter(pool=mock_pool)

        assert writer._pool is mock_pool
        assert writer._normalizer is None

    def test_init_with_normalizer(self):
        """Test Neo4jWriter initializes with normalizer."""
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        mock_pool = MagicMock()
        mock_normalizer = MagicMock()

        writer = Neo4jWriter(pool=mock_pool, relation_type_normalizer=mock_normalizer)

        assert writer._normalizer is mock_normalizer


class TestNeo4jWriterProperties:
    """Tests for Neo4jWriter properties."""

    @pytest.fixture
    def writer(self):
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        return Neo4jWriter(pool=MagicMock())

    def test_entity_repo_property(self, writer):
        """Test entity_repo property returns repository."""
        repo = writer.entity_repo
        assert repo is not None

    def test_article_repo_property(self, writer):
        """Test article_repo property returns repository."""
        repo = writer.article_repo
        assert repo is not None


class TestNeo4jWriterEnsureConstraints:
    """Tests for ensure_constraints()."""

    @pytest.fixture
    def writer(self):
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        writer = Neo4jWriter(pool=MagicMock())
        writer._entity_repo.ensure_constraints = AsyncMock()
        return writer

    @pytest.mark.asyncio
    async def test_ensure_constraints_calls_repo(self, writer):
        """Test ensure_constraints calls entity repo."""
        await writer.ensure_constraints()

        writer._entity_repo.ensure_constraints.assert_called_once()


class TestNeo4jWriterWrite:
    """Tests for write()."""

    @pytest.fixture
    def mock_state(self):
        """Create mock pipeline state."""
        return {
            "article_id": "test-article-id",
            "raw": MagicMock(
                title="Test Article",
                publish_time=datetime.now(UTC),
                url="https://example.com/test",
            ),
            "cleaned": {"title": "Cleaned Title"},
            "category": MagicMock(value="tech"),
            "score": 0.85,
            "entities": [
                {"name": "Entity 1", "type": "PERSON", "role": "author"},
                {"name": "Entity 2", "type": "ORG", "role": "publisher"},
            ],
            "relations": [],
            "merged_source_ids": [],
        }

    @pytest.fixture
    def writer(self):
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        writer = Neo4jWriter(pool=MagicMock())
        writer._article_repo.create_article = AsyncMock(return_value="neo4j-article-id")
        writer._article_repo.find_article_by_pg_id = AsyncMock(return_value=None)
        writer._article_repo.create_followed_by_relation = AsyncMock()
        writer._entity_repo.merge_entities_batch = AsyncMock(
            return_value={"created": 2, "updated": 0}
        )
        writer._entity_repo.add_aliases_batch = AsyncMock()
        writer._entity_repo.find_entity = AsyncMock(
            return_value={"neo4j_id": "entity-id", "canonical_name": "Entity 1"}
        )
        writer._entity_repo.find_entities_by_keys = AsyncMock(
            return_value=[
                {"neo4j_id": "entity-id-1", "canonical_name": "Entity 1", "type": "PERSON"},
                {"neo4j_id": "entity-id-2", "canonical_name": "Entity 2", "type": "ORG"},
            ]
        )
        writer._entity_repo.merge_mentions_batch = AsyncMock(return_value=2)
        writer._entity_repo.add_alias = AsyncMock()
        return writer

    @pytest.mark.asyncio
    async def test_write_raises_without_article_id(self, writer):
        """Test write raises ValueError without article_id."""
        state = {"raw": MagicMock(title="Test")}

        with pytest.raises(ValueError, match="article_id"):
            await writer.write(state)

    @pytest.mark.asyncio
    async def test_write_creates_article(self, writer, mock_state):
        """Test write creates article node."""
        result = await writer.write(mock_state)

        writer._article_repo.create_article.assert_called_once()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_write_processes_entities(self, writer, mock_state):
        """Test write processes entities."""
        result = await writer.write(mock_state)

        writer._entity_repo.merge_entities_batch.assert_called_once()
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_write_handles_empty_entities(self, writer, mock_state):
        """Test write handles empty entities list."""
        mock_state["entities"] = []

        result = await writer.write(mock_state)

        writer._entity_repo.merge_entities_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_creates_followed_relations(self, writer, mock_state):
        """Test write creates FOLLOWED_BY relations."""
        mock_state["merged_source_ids"] = ["source-1", "source-2"]
        mock_state["raw"].publish_time = datetime.now(UTC)

        await writer.write(mock_state)

        assert writer._article_repo.create_followed_by_relation.call_count == 2


class TestNeo4jWriterCleanup:
    """Tests for cleanup operations."""

    @pytest.fixture
    def writer(self):
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        writer = Neo4jWriter(pool=MagicMock())
        writer._entity_repo.delete_orphan_entities = AsyncMock(return_value=10)
        writer._article_repo.delete_old_articles = AsyncMock(return_value=50)
        return writer

    @pytest.mark.asyncio
    async def test_cleanup_orphan_entities(self, writer):
        """Test cleanup_orphan_entities calls repo."""
        result = await writer.cleanup_orphan_entities()

        writer._entity_repo.delete_orphan_entities.assert_called_once()
        assert result == 10

    @pytest.mark.asyncio
    async def test_archive_old_articles(self, writer):
        """Test archive_old_articles deletes old articles."""
        result = await writer.archive_old_articles(days=30)

        writer._article_repo.delete_old_articles.assert_called_once_with(30)
        writer._entity_repo.delete_orphan_entities.assert_called_once()
        assert result == 50


class TestNeo4jWriterResolveCanonicalName:
    """Tests for _resolve_canonical_name()."""

    @pytest.fixture
    def writer(self):
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        writer = Neo4jWriter(pool=MagicMock())
        writer._entity_repo.find_entity = AsyncMock(return_value=None)
        return writer

    @pytest.mark.asyncio
    async def test_resolve_canonical_name_returns_existing(self, writer):
        """Test _resolve_canonical_name returns existing name."""
        writer._entity_repo.find_entity.return_value = {
            "neo4j_id": "id",
            "canonical_name": "Canonical Name",
        }

        result = await writer._resolve_canonical_name("Test Name", "PERSON")

        assert result == "Canonical Name"

    @pytest.mark.asyncio
    async def test_resolve_canonical_name_returns_input_for_new(self, writer):
        """Test _resolve_canonical_name returns input for new entity."""
        writer._entity_repo.find_entity.return_value = None

        result = await writer._resolve_canonical_name("New Entity", "ORG")

        assert result == "New Entity"


class TestNeo4jWriterWriteEntityRelations:
    """Tests for _write_entity_relations()."""

    @pytest.fixture
    def writer(self):
        from modules.knowledge.graph.neo4j_writer import Neo4jWriter

        writer = Neo4jWriter(pool=MagicMock())
        writer._entity_repo.merge_relation = AsyncMock()
        return writer

    @pytest.mark.asyncio
    async def test_write_entity_relations_creates_relations(self, writer):
        """Test _write_entity_relations creates relations."""
        relations = [
            {"source": "Entity A", "target": "Entity B", "relation_type": "WORKS_FOR"},
        ]
        entity_name_to_id = {
            "Entity A": "neo4j-id-a",
            "Entity B": "neo4j-id-b",
        }

        count = await writer._write_entity_relations(relations, entity_name_to_id)

        assert count == 1
        writer._entity_repo.merge_relation.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_entity_relations_skips_missing_entities(self, writer):
        """Test _write_entity_relations skips when entity not found."""
        relations = [
            {"source": "Entity A", "target": "Entity C", "relation_type": "WORKS_FOR"},
        ]
        entity_name_to_id = {
            "Entity A": "neo4j-id-a",
            # Entity C not in map
        }

        count = await writer._write_entity_relations(relations, entity_name_to_id)

        assert count == 0
        writer._entity_repo.merge_relation.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_entity_relations_handles_empty_list(self, writer):
        """Test _write_entity_relations handles empty list."""
        count = await writer._write_entity_relations([], {})

        assert count == 0
