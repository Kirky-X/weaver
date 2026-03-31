# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4jWriter."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.knowledge.graph.neo4j_writer import Neo4jWriter
from modules.processing.pipeline.state import PipelineState


class TestNeo4jWriterInit:
    """Test Neo4jWriter initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        writer = Neo4jWriter(mock_pool)

        assert writer._pool == mock_pool
        assert writer._entity_repo is not None
        assert writer._article_repo is not None

    def test_entity_repo_property(self):
        """Test entity_repo property."""
        mock_pool = MagicMock()
        writer = Neo4jWriter(mock_pool)

        repo = writer.entity_repo
        assert repo is not None

    def test_article_repo_property(self):
        """Test article_repo property."""
        mock_pool = MagicMock()
        writer = Neo4jWriter(mock_pool)

        repo = writer.article_repo
        assert repo is not None


class TestNeo4jWriterEnsureConstraints:
    """Test ensure_constraints method."""

    @pytest.fixture
    def writer(self):
        """Create Neo4jWriter instance."""
        writer = Neo4jWriter(MagicMock())
        writer._entity_repo = MagicMock()
        writer._entity_repo.ensure_constraints = AsyncMock()
        return writer

    @pytest.mark.asyncio
    async def test_ensure_constraints(self, writer):
        """Test ensure_constraints calls entity_repo."""
        await writer.ensure_constraints()
        writer._entity_repo.ensure_constraints.assert_called_once()


class TestNeo4jWriterWrite:
    """Test write method."""

    @pytest.fixture
    def writer(self):
        """Create Neo4jWriter instance with mocked repos."""
        writer = Neo4jWriter(MagicMock())
        writer._entity_repo = MagicMock()
        writer._article_repo = MagicMock()
        return writer

    @pytest.mark.asyncio
    async def test_write_no_article_id(self, writer):
        """Test write raises when no article_id."""
        state = PipelineState(raw=MagicMock())

        with pytest.raises(ValueError, match="article_id not found"):
            await writer.write(state)

    @pytest.mark.asyncio
    async def test_write_creates_article(self, writer):
        """Test write creates article node."""
        article_id = str(uuid.uuid4())

        writer._article_repo.create_article = AsyncMock(return_value="neo4j_article_id")
        writer._entity_repo.find_entity = AsyncMock(return_value=None)
        writer._entity_repo.merge_entity = AsyncMock(return_value="entity_id")
        writer._entity_repo.add_alias = AsyncMock()
        writer._entity_repo.merge_mentions_relation = AsyncMock()

        raw = MagicMock()
        raw.title = "Test Article"
        raw.body = "Test body"
        raw.url = "https://example.com/test"
        raw.publish_time = datetime.now(UTC)
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["article_id"] = article_id
        state["cleaned"] = {"title": "Cleaned Title", "body": "Cleaned Body"}
        state["category"] = "科技"
        state["score"] = 0.85
        state["entities"] = []

        result = await writer.write(state)

        writer._article_repo.create_article.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_with_entities(self, writer):
        """Test write processes entities."""
        article_id = str(uuid.uuid4())

        writer._article_repo.create_article = AsyncMock(return_value="neo4j_article_id")
        writer._entity_repo.find_entity = AsyncMock(
            return_value={
                "neo4j_id": "entity_id",
                "canonical_name": "张三",
            }
        )
        writer._entity_repo.find_entities_batch = AsyncMock(
            return_value=[
                {"neo4j_id": "entity_id_1", "canonical_name": "张三"},
                {"neo4j_id": "entity_id_2", "canonical_name": "OpenAI"},
            ]
        )
        writer._entity_repo.merge_entities_batch = AsyncMock(
            return_value={"created": 2, "updated": 0}
        )
        writer._entity_repo.add_aliases_batch = AsyncMock()
        writer._entity_repo.merge_mentions_batch = AsyncMock(return_value=2)

        raw = MagicMock()
        raw.title = "Test Article"
        raw.body = "Test body"
        raw.url = "https://example.com/test"
        raw.publish_time = datetime.now(UTC)
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["article_id"] = article_id
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        state["entities"] = [
            {"name": "张三", "type": "人物", "role": "主角"},
            {"name": "OpenAI", "type": "组织机构", "role": "提及"},
        ]

        result = await writer.write(state)

        assert len(result) == 2  # 2 unique entities → 2 IDs

    @pytest.mark.asyncio
    async def test_write_entity_without_name_skipped(self, writer):
        """Test write skips entities without name."""
        article_id = str(uuid.uuid4())

        writer._article_repo.create_article = AsyncMock(return_value="neo4j_article_id")
        writer._entity_repo.merge_entity = AsyncMock()

        raw = MagicMock()
        raw.title = "Test Article"
        raw.body = "Test body"
        raw.url = "https://example.com/test"
        raw.publish_time = datetime.now(UTC)
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["article_id"] = article_id
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        state["entities"] = [
            {"type": "人物", "role": "主角"},
        ]

        result = await writer.write(state)

        assert len(result) == 0
        writer._entity_repo.merge_entity.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_entity_without_type_skipped(self, writer):
        """Test write skips entities without type."""
        article_id = str(uuid.uuid4())

        writer._article_repo.create_article = AsyncMock(return_value="neo4j_article_id")
        writer._entity_repo.merge_entity = AsyncMock()

        raw = MagicMock()
        raw.title = "Test Article"
        raw.body = "Test body"
        raw.url = "https://example.com/test"
        raw.publish_time = datetime.now(UTC)
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["article_id"] = article_id
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        state["entities"] = [
            {"name": "张三", "role": "主角"},
        ]

        result = await writer.write(state)

        assert len(result) == 0
        writer._entity_repo.merge_entity.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_entity_merge_failure_handled(self, writer):
        """Test write handles entity merge failure."""
        article_id = str(uuid.uuid4())

        writer._article_repo.create_article = AsyncMock(return_value="neo4j_article_id")
        writer._entity_repo.find_entity = AsyncMock(return_value=None)
        writer._entity_repo.merge_entity = AsyncMock(side_effect=Exception("Merge error"))

        raw = MagicMock()
        raw.title = "Test Article"
        raw.body = "Test body"
        raw.url = "https://example.com/test"
        raw.publish_time = datetime.now(UTC)
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["article_id"] = article_id
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        state["entities"] = [
            {"name": "张三", "type": "人物"},
        ]

        result = await writer.write(state)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_write_with_merged_sources(self, writer):
        """Test write creates FOLLOWED_BY relations for merged articles."""
        article_id = str(uuid.uuid4())
        source_id = str(uuid.uuid4())

        writer._article_repo.create_article = AsyncMock(return_value="neo4j_article_id")
        writer._article_repo.find_article_by_pg_id = AsyncMock(
            return_value={"publish_time": datetime.now(UTC) - timedelta(hours=2)}
        )
        writer._article_repo.create_followed_by_relation = AsyncMock()

        raw = MagicMock()
        raw.title = "Test Article"
        raw.body = "Test body"
        raw.url = "https://example.com/test"
        raw.publish_time = datetime.now(UTC)
        raw.source_host = "example.com"

        state = PipelineState(raw=raw)
        state["article_id"] = article_id
        state["cleaned"] = {"title": "Title", "body": "Body"}
        state["category"] = "科技"
        state["entities"] = []
        state["merged_source_ids"] = [source_id]

        await writer.write(state)

        writer._article_repo.create_followed_by_relation.assert_called_once()


class TestNeo4jWriterWriteEntities:
    """Test _write_entities method."""

    @pytest.fixture
    def writer(self):
        """Create Neo4jWriter instance."""
        writer = Neo4jWriter(MagicMock())
        writer._entity_repo = MagicMock()
        return writer

    @pytest.mark.asyncio
    async def test_write_entities_empty(self, writer):
        """Test write entities with empty list."""
        state = PipelineState(raw=MagicMock())
        state["language"] = "zh"

        entity_ids = await writer._write_entities(
            article_neo4j_id="article_id",
            entities=[],
            state=state,
        )

        assert entity_ids == []

    @pytest.mark.asyncio
    async def test_write_entities_adds_alias(self, writer):
        """Test write entities adds alias when name differs."""
        writer._entity_repo.find_entity = AsyncMock(
            return_value={
                "neo4j_id": "entity_id",
                "canonical_name": "张三",
            }
        )
        writer._entity_repo.find_entities_batch = AsyncMock(
            return_value=[
                {"neo4j_id": "entity_id", "canonical_name": "张三", "id": "uuid-123"},
            ]
        )
        writer._entity_repo.merge_entities_batch = AsyncMock(
            return_value={"created": 1, "updated": 0}
        )
        writer._entity_repo.add_aliases_batch = AsyncMock()
        writer._entity_repo.merge_mentions_batch = AsyncMock(return_value=1)

        state = PipelineState(raw=MagicMock())
        state["language"] = "zh"
        state["article_id"] = "test_article_id"

        entity_ids = await writer._write_entities(
            article_neo4j_id="article_id",
            entities=[
                {"name": "张三", "type": "人物", "description": "测试人物"},
            ],
            state=state,
        )

        assert len(entity_ids) == 1
        assert entity_ids[0] == "entity_id"

    @pytest.mark.asyncio
    async def test_write_entities_handles_mentions_error(self, writer):
        """Test write entities handles MENTIONS relation error."""
        writer._entity_repo.find_entity = AsyncMock(
            return_value={
                "neo4j_id": "entity_id",
                "canonical_name": "张三",
            }
        )
        writer._entity_repo.find_entities_batch = AsyncMock(
            return_value=[
                {"neo4j_id": "entity_id", "canonical_name": "张三", "id": "uuid-123"},
            ]
        )
        writer._entity_repo.merge_entities_batch = AsyncMock(
            return_value={"created": 1, "updated": 0}
        )
        writer._entity_repo.add_aliases_batch = AsyncMock()
        writer._entity_repo.merge_mentions_batch = AsyncMock(
            side_effect=Exception("Relation error")
        )

        state = PipelineState(raw=MagicMock())
        state["language"] = "zh"
        state["article_id"] = "test_article_id"

        entity_ids = await writer._write_entities(
            article_neo4j_id="article_id",
            entities=[
                {"name": "张三", "type": "人物"},
            ],
            state=state,
        )

        assert len(entity_ids) == 1


class TestNeo4jWriterResolveCanonicalName:
    """Test _resolve_canonical_name method."""

    @pytest.fixture
    def writer(self):
        """Create Neo4jWriter instance."""
        writer = Neo4jWriter(MagicMock())
        writer._entity_repo = MagicMock()
        return writer

    @pytest.mark.asyncio
    async def test_resolve_existing_entity(self, writer):
        """Test resolve returns existing entity name."""
        writer._entity_repo.find_entity = AsyncMock(
            return_value={
                "canonical_name": "张三",
            }
        )

        result = await writer._resolve_canonical_name("张三", "人物")

        assert result == "张三"

    @pytest.mark.asyncio
    async def test_resolve_new_entity(self, writer):
        """Test resolve returns provided name for new entity."""
        writer._entity_repo.find_entity = AsyncMock(return_value=None)

        result = await writer._resolve_canonical_name("李四", "人物")

        assert result == "李四"


class TestNeo4jWriterCreateFollowedRelations:
    """Test _create_followed_relations method."""

    @pytest.fixture
    def writer(self):
        """Create Neo4jWriter instance."""
        writer = Neo4jWriter(MagicMock())
        writer._article_repo = MagicMock()
        return writer

    @pytest.mark.asyncio
    async def test_create_followed_relations(self, writer):
        """Test create FOLLOWED_BY relations."""
        publish_time = datetime.now(UTC)
        source_time = publish_time - timedelta(hours=2)

        writer._article_repo.find_article_by_pg_id = AsyncMock(
            return_value={
                "publish_time": source_time,
            }
        )
        writer._article_repo.create_followed_by_relation = AsyncMock()

        await writer._create_followed_relations(
            article_id="target_id",
            source_ids=["source_id"],
            publish_time=publish_time,
        )

        writer._article_repo.create_followed_by_relation.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_followed_relations_no_source_article(self, writer):
        """Test create FOLLOWED_BY when source article not found."""
        writer._article_repo.find_article_by_pg_id = AsyncMock(return_value=None)
        writer._article_repo.create_followed_by_relation = AsyncMock()

        await writer._create_followed_relations(
            article_id="target_id",
            source_ids=["source_id"],
            publish_time=datetime.now(UTC),
        )

        writer._article_repo.create_followed_by_relation.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_followed_relations_handles_error(self, writer):
        """Test create FOLLOWED_BY handles errors."""
        writer._article_repo.find_article_by_pg_id = AsyncMock(side_effect=Exception("Find error"))

        await writer._create_followed_relations(
            article_id="target_id",
            source_ids=["source_id"],
            publish_time=datetime.now(UTC),
        )

    @pytest.mark.asyncio
    async def test_create_followed_relations_multiple_sources(self, writer):
        """Test create FOLLOWED_BY for multiple sources."""
        writer._article_repo.find_article_by_pg_id = AsyncMock(
            return_value={
                "publish_time": datetime.now(UTC) - timedelta(hours=1),
            }
        )
        writer._article_repo.create_followed_by_relation = AsyncMock()

        await writer._create_followed_relations(
            article_id="target_id",
            source_ids=["source1", "source2", "source3"],
            publish_time=datetime.now(UTC),
        )

        assert writer._article_repo.create_followed_by_relation.call_count == 3


class TestNeo4jWriterCleanupOrphanEntities:
    """Test cleanup_orphan_entities method."""

    @pytest.fixture
    def writer(self):
        """Create Neo4jWriter instance."""
        writer = Neo4jWriter(MagicMock())
        writer._entity_repo = MagicMock()
        return writer

    @pytest.mark.asyncio
    async def test_cleanup_orphan_entities(self, writer):
        """Test cleanup orphan entities."""
        writer._entity_repo.delete_orphan_entities = AsyncMock(return_value=5)

        result = await writer.cleanup_orphan_entities()

        assert result == 5
        writer._entity_repo.delete_orphan_entities.assert_called_once()


class TestNeo4jWriterArchiveOldArticles:
    """Test archive_old_articles method."""

    @pytest.fixture
    def writer(self):
        """Create Neo4jWriter instance."""
        writer = Neo4jWriter(MagicMock())
        writer._entity_repo = MagicMock()
        writer._article_repo = MagicMock()
        writer._entity_repo.delete_orphan_entities = AsyncMock(return_value=3)
        writer._article_repo.delete_old_articles = AsyncMock(return_value=10)
        return writer

    @pytest.mark.asyncio
    async def test_archive_old_articles_default_days(self, writer):
        """Test archive old articles with default days."""
        result = await writer.archive_old_articles()

        assert result == 10
        writer._article_repo.delete_old_articles.assert_called_once_with(90)

    @pytest.mark.asyncio
    async def test_archive_old_articles_custom_days(self, writer):
        """Test archive old articles with custom days."""
        result = await writer.archive_old_articles(days=30)

        assert result == 10
        writer._article_repo.delete_old_articles.assert_called_once_with(30)

    @pytest.mark.asyncio
    async def test_archive_old_articles_cleans_orphans(self, writer):
        """Test archive old articles cleans orphan entities."""
        await writer.archive_old_articles()

        writer._entity_repo.delete_orphan_entities.assert_called_once()


from datetime import timedelta
