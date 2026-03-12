"""Integration tests for VectorRepo."""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from modules.storage.vector_repo import VectorRepo, SimilarArticle, SimilarEntity


class TestSimilarArticle:
    """Tests for SimilarArticle dataclass."""

    def test_similar_article_creation(self):
        """Test SimilarArticle can be created."""
        article = SimilarArticle(
            article_id="article-123",
            category="tech",
            similarity=0.85,
        )
        assert article.article_id == "article-123"
        assert article.category == "tech"
        assert article.similarity == 0.85

    def test_similar_article_with_none_category(self):
        """Test SimilarArticle with None category."""
        article = SimilarArticle(
            article_id="article-456",
            category=None,
            similarity=0.9,
        )
        assert article.category is None


class TestSimilarEntity:
    """Tests for SimilarEntity dataclass."""

    def test_similar_entity_creation(self):
        """Test SimilarEntity can be created."""
        entity = SimilarEntity(
            neo4j_id="entity-123",
            similarity=0.92,
        )
        assert entity.neo4j_id == "entity-123"
        assert entity.similarity == 0.92


class TestVectorRepoIntegration:
    """Integration tests for VectorRepo with PostgreSQL."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def vector_repo(self, mock_pool):
        """Create VectorRepo instance."""
        return VectorRepo(mock_pool)

    def test_vector_repo_initialization(self, vector_repo, mock_pool):
        """Test VectorRepo initializes correctly."""
        assert vector_repo._pool is mock_pool

    @pytest.mark.asyncio
    async def test_upsert_article_vectors(self, vector_repo, mock_pool):
        """Test upsert_article_vectors creates vectors."""
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        title_embedding = [0.1] * 1536
        content_embedding = [0.2] * 1536

        await vector_repo.upsert_article_vectors(
            article_id=article_id,
            title_embedding=title_embedding,
            content_embedding=content_embedding,
            model_id="text-embedding-3-large",
        )

        mock_session.add.assert_called()

    @pytest.mark.asyncio
    async def test_upsert_article_vectors_update_existing(self, vector_repo, mock_pool):
        """Test upsert_article_vectors updates existing vectors."""
        mock_existing = MagicMock()
        mock_existing.embedding = [0.0] * 1536

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_existing
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        title_embedding = [0.1] * 1536

        await vector_repo.upsert_article_vectors(
            article_id=article_id,
            title_embedding=title_embedding,
            content_embedding=None,
        )

        assert mock_existing.embedding == title_embedding

    @pytest.mark.asyncio
    async def test_upsert_article_vectors_skip_none(self, vector_repo, mock_pool):
        """Test upsert_article_vectors skips None embeddings."""
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()

        await vector_repo.upsert_article_vectors(
            article_id=article_id,
            title_embedding=None,
            content_embedding=None,
        )

        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_similar(self, vector_repo, mock_pool):
        """Test find_similar returns similar articles."""
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            MagicMock(article_id="article-1", category="tech", similarity=0.9),
            MagicMock(article_id="article-2", category="tech", similarity=0.85),
        ]))

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_pool.session.return_value = mock_session

        embedding = [0.1] * 1536

        result = await vector_repo.find_similar(
            embedding=embedding,
            category="tech",
            threshold=0.8,
            limit=10,
        )

        assert len(result) == 2
        assert result[0].article_id == "article-1"
        assert result[0].similarity == 0.9

    @pytest.mark.asyncio
    async def test_find_similar_with_model_filter(self, vector_repo, mock_pool):
        """Test find_similar with model_id filter."""
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_pool.session.return_value = mock_session

        embedding = [0.1] * 1536

        result = await vector_repo.find_similar(
            embedding=embedding,
            category=None,
            threshold=0.8,
            limit=10,
            model_id="text-embedding-3-large",
        )

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_upsert_entity_vectors(self, vector_repo, mock_pool):
        """Test upsert_entity_vectors creates entity vectors."""
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        entities = [
            ("entity-1", [0.1] * 1536),
            ("entity-2", [0.2] * 1536),
        ]

        await vector_repo.upsert_entity_vectors(entities)

        assert mock_session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_upsert_entity_vectors_update_existing(self, vector_repo, mock_pool):
        """Test upsert_entity_vectors updates existing vectors."""
        mock_existing = MagicMock()
        mock_existing.embedding = [0.0] * 1536

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_existing
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        entities = [("entity-1", [0.5] * 1536)]

        await vector_repo.upsert_entity_vectors(entities)

        assert mock_existing.embedding == [0.5] * 1536

    @pytest.mark.asyncio
    async def test_upsert_entity_vector_single(self, vector_repo, mock_pool):
        """Test upsert_entity_vector for single entity."""
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await vector_repo.upsert_entity_vector(
            neo4j_id="entity-single",
            embedding=[0.3] * 1536,
        )

        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_similar_entities(self, vector_repo, mock_pool):
        """Test find_similar_entities returns similar entities."""
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            MagicMock(neo4j_id="entity-1", similarity=0.95),
            MagicMock(neo4j_id="entity-2", similarity=0.88),
        ]))

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_pool.session.return_value = mock_session

        embedding = [0.1] * 1536

        result = await vector_repo.find_similar_entities(
            embedding=embedding,
            threshold=0.85,
            limit=5,
        )

        assert len(result) == 2
        assert result[0].neo4j_id == "entity-1"
        assert result[0].similarity == 0.95

    @pytest.mark.asyncio
    async def test_find_similar_entities_empty_result(self, vector_repo, mock_pool):
        """Test find_similar_entities returns empty list when no matches."""
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_pool.session.return_value = mock_session

        embedding = [0.1] * 1536

        result = await vector_repo.find_similar_entities(
            embedding=embedding,
            threshold=0.99,
            limit=5,
        )

        assert len(result) == 0
