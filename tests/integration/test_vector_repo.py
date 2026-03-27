# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for VectorRepo - requires real PostgreSQL database."""

import os
import uuid

import pytest
from sqlalchemy import text

from modules.storage.vector_repo import SimilarArticle, SimilarEntity, VectorRepo


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
    async def pool(self):
        """Create a fresh PostgreSQL pool for each test."""
        from core.db.postgres import PostgresPool

        dsn = os.getenv(
            "WEAVER_POSTGRES__DSN",
            os.getenv(
                "POSTGRES_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver"
            ),
        )
        pool = PostgresPool(dsn)
        await pool.startup()
        yield pool
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_vector_repo_initialization(self, pool):
        """Test VectorRepo initializes correctly with real pool."""
        repo = VectorRepo(pool)
        assert repo._pool is pool

    @pytest.mark.asyncio
    async def test_upsert_article_vectors(self, pool):
        """Test upsert_article_vectors creates vectors."""
        vector_repo = VectorRepo(pool)
        article_id = uuid.uuid4()

        # Create test article
        async with pool.session_context() as session:
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, is_news, title, body, is_merged, verified_by_sources)
                    VALUES (:id, :url, :is_news, :title, :body, :is_merged, :verified_by)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{article_id}",
                    "is_news": True,
                    "title": "Test Article",
                    "body": "Test body content",
                    "is_merged": False,
                    "verified_by": 0,
                },
            )

        try:
            title_embedding = [0.1] * 1024
            content_embedding = [0.2] * 1024

            await vector_repo.upsert_article_vectors(
                article_id=article_id,
                title_embedding=title_embedding,
                content_embedding=content_embedding,
                model_id="text-embedding-3-large",
            )
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE id = :id"),
                    {"id": article_id},
                )

    @pytest.mark.asyncio
    async def test_find_similar(self, pool):
        """Test find_similar returns similar articles."""
        vector_repo = VectorRepo(pool)
        article_id = uuid.uuid4()

        # Create test article
        async with pool.session_context() as session:
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, is_news, title, body, is_merged, verified_by_sources)
                    VALUES (:id, :url, :is_news, :title, :body, :is_merged, :verified_by)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{article_id}",
                    "is_news": True,
                    "title": "Test Article",
                    "body": "Test body content",
                    "is_merged": False,
                    "verified_by": 0,
                },
            )

        try:
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
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
