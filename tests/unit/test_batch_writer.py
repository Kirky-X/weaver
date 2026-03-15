"""Unit tests for batch writer module."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.graph_store.batch_writer import (
    Neo4jBatchWriter,
    BatchResult,
    EntityBatch,
    RelationBatch,
)


class TestBatchResult:
    """Test BatchResult dataclass."""

    def test_initialization(self):
        """Test BatchResult initialization."""
        result = BatchResult(
            total=100,
            created=80,
            updated=15,
            skipped=5,
        )

        assert result.total == 100
        assert result.created == 80
        assert result.updated == 15
        assert result.skipped == 5
        assert result.errors == []

    def test_success_rate(self):
        """Test success rate calculation."""
        result = BatchResult(total=100, created=90, updated=5, skipped=5)
        assert result.success_rate == 0.95

        result_empty = BatchResult(total=0, created=0, updated=0, skipped=0)
        assert result_empty.success_rate == 1.0


class TestEntityBatch:
    """Test EntityBatch dataclass."""

    def test_initialization(self):
        """Test EntityBatch initialization."""
        batch = EntityBatch(
            canonical_name="Test Entity",
            entity_type="人物",
            description="Test description",
            aliases=["Alias1", "Alias2"],
        )

        assert batch.canonical_name == "Test Entity"
        assert batch.entity_type == "人物"
        assert batch.description == "Test description"
        assert len(batch.aliases) == 2


class TestRelationBatch:
    """Test RelationBatch dataclass."""

    def test_initialization(self):
        """Test RelationBatch initialization."""
        batch = RelationBatch(
            from_name="Entity1",
            from_type="人物",
            to_name="Entity2",
            to_type="组织机构",
            relation_type="工作于",
        )

        assert batch.from_name == "Entity1"
        assert batch.to_name == "Entity2"
        assert batch.relation_type == "工作于"


class TestNeo4jBatchWriter:
    """Test Neo4jBatchWriter class."""

    def test_init_default(self):
        """Test default initialization."""
        mock_pool = MagicMock()
        writer = Neo4jBatchWriter(mock_pool)

        assert writer._pool == mock_pool
        assert writer._entity_batch_size == 1000
        assert writer._relation_batch_size == 2000

    def test_init_custom(self):
        """Test custom initialization."""
        mock_pool = MagicMock()
        writer = Neo4jBatchWriter(
            mock_pool,
            entity_batch_size=500,
            relation_batch_size=1000,
        )

        assert writer._entity_batch_size == 500
        assert writer._relation_batch_size == 1000

    @pytest.mark.asyncio
    async def test_merge_entities_batch_empty(self):
        """Test batch merge with empty list."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])
        writer = Neo4jBatchWriter(mock_pool)

        result = await writer.merge_entities_batch([])

        assert result.total == 0
        assert result.created == 0

    @pytest.mark.asyncio
    async def test_merge_entities_batch_single(self):
        """Test batch merge with single entity."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[
            {"created": 1, "updated": 0}
        ])
        writer = Neo4jBatchWriter(mock_pool)

        entities = [
            EntityBatch(canonical_name="Entity1", entity_type="人物")
        ]

        result = await writer.merge_entities_batch(entities)

        assert result.total == 1
        assert result.created == 1

    @pytest.mark.asyncio
    async def test_merge_entities_batch_multiple(self):
        """Test batch merge with multiple entities."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[
            {"created": 2, "updated": 0}
        ])
        writer = Neo4jBatchWriter(mock_pool)

        entities = [
            EntityBatch(canonical_name="Entity1", entity_type="人物"),
            EntityBatch(canonical_name="Entity2", entity_type="组织机构"),
        ]

        result = await writer.merge_entities_batch(entities)

        assert result.total == 2
        assert result.created == 2

    @pytest.mark.asyncio
    async def test_merge_relations_batch(self):
        """Test batch relation merge."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[
            {"total": 2}
        ])
        writer = Neo4jBatchWriter(mock_pool)

        relations = [
            RelationBatch(
                from_name="E1", from_type="人物",
                to_name="E2", to_type="组织机构",
                relation_type="工作于"
            ),
        ]

        result = await writer.merge_relations_batch(relations)

        assert result.total == 1

    @pytest.mark.asyncio
    async def test_add_aliases_batch(self):
        """Test batch alias addition."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[
            {"updated": 2}
        ])
        writer = Neo4jBatchWriter(mock_pool)

        aliases = [
            {"canonical_name": "Entity1", "entity_type": "人物", "alias": "Alias1"},
            {"canonical_name": "Entity2", "entity_type": "组织机构", "alias": "Alias2"},
        ]

        result = await writer.add_aliases_batch(aliases)

        assert result.updated == 2

    @pytest.mark.asyncio
    async def test_update_embeddings_batch(self):
        """Test batch embedding update."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[
            {"updated": 2}
        ])
        writer = Neo4jBatchWriter(mock_pool)

        embeddings = [
            {"entity_name": "Entity1", "entity_type": "人物", "embedding": [0.1, 0.2]},
            {"entity_name": "Entity2", "entity_type": "组织机构", "embedding": [0.3, 0.4]},
        ]

        result = await writer.update_entity_embeddings_batch(embeddings)

        assert result.updated == 2

    @pytest.mark.asyncio
    async def test_delete_entities_batch(self):
        """Test batch entity deletion."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[
            {"deleted": 2}
        ])
        writer = Neo4jBatchWriter(mock_pool)

        deleted = await writer.delete_entities_batch(["id1", "id2"])

        assert deleted == 2

    @pytest.mark.asyncio
    async def test_create_articles_batch(self):
        """Test batch article creation."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[
            {"created": 2, "updated": 0}
        ])
        writer = Neo4jBatchWriter(mock_pool)

        articles = [
            {"pg_id": "1", "title": "Article 1", "category": "tech"},
            {"pg_id": "2", "title": "Article 2", "category": "news"},
        ]

        result = await writer.create_article_entities_batch(articles)

        assert result.created == 2

    def test_chunk(self):
        """Test chunking utility."""
        mock_pool = MagicMock()
        writer = Neo4jBatchWriter(mock_pool)

        items = list(range(10))
        chunks = list(writer._chunk(items, 3))

        assert len(chunks) == 4
        assert chunks[0] == [0, 1, 2]
        assert chunks[3] == [9]

    def test_chunk_larger_than_size(self):
        """Test chunking with size larger than list."""
        mock_pool = MagicMock()
        writer = Neo4jBatchWriter(mock_pool)

        items = [1, 2, 3]
        chunks = list(writer._chunk(items, 10))

        assert len(chunks) == 1
        assert chunks[0] == [1, 2, 3]
