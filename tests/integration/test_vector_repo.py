"""Integration tests for VectorRepo - requires real PostgreSQL database."""

import pytest
import uuid

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


@pytest.mark.skip(reason="Requires real PostgreSQL database - use conftest postgres_pool fixture")
class TestVectorRepoIntegration:
    """Integration tests for VectorRepo with PostgreSQL."""

    @pytest.fixture
    def vector_repo(self, postgres_pool):
        """Create VectorRepo instance with real pool."""
        return VectorRepo(postgres_pool)

    def test_vector_repo_initialization(self, postgres_pool):
        """Test VectorRepo initializes correctly with real pool."""
        repo = VectorRepo(postgres_pool)
        assert repo._pool is postgres_pool

    @pytest.mark.asyncio
    async def test_upsert_article_vectors(self, vector_repo):
        """Test upsert_article_vectors creates vectors."""
        article_id = uuid.uuid4()
        title_embedding = [0.1] * 1024
        content_embedding = [0.2] * 1024

        await vector_repo.upsert_article_vectors(
            article_id=article_id,
            title_embedding=title_embedding,
            content_embedding=content_embedding,
            model_id="text-embedding-3-large",
        )

    @pytest.mark.asyncio
    async def test_find_similar(self, vector_repo):
        """Test find_similar returns similar articles."""
        article_id = uuid.uuid4()
        embedding = [0.1] * 1024

        await vector_repo.upsert_article_vectors(
            article_id=article_id,
            title_embedding=embedding,
            content_embedding=None,
        )

        results = await vector_repo.find_similar(
            embedding=embedding,
            limit=5,
        )
        assert isinstance(results, list)
