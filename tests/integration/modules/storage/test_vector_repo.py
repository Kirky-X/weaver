# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Integration tests for VectorRepo - uses fallback databases."""

import uuid

import pytest
from sqlalchemy import text

from core.db import create_vector_query_builder
from core.models.shared import ArticleSearchResultView, EntitySearchResultView
from modules.storage.postgres.vector_repo import VectorRepo


class TestArticleSearchResultView:
    """Tests for ArticleSearchResultView model."""

    def test_article_search_result_creation(self):
        """Test ArticleSearchResultView can be created."""
        article = ArticleSearchResultView(
            article_id="article-123",
            category="tech",
            similarity=0.85,
        )
        assert article.article_id == "article-123"
        assert article.category == "tech"
        assert article.similarity == 0.85

    def test_article_search_result_with_none_category(self):
        """Test ArticleSearchResultView with None category."""
        article = ArticleSearchResultView(
            article_id="article-456",
            category=None,
            similarity=0.9,
        )
        assert article.category is None


class TestEntitySearchResultView:
    """Tests for EntitySearchResultView model."""

    def test_entity_search_result_creation(self):
        """Test EntitySearchResultView can be created."""
        entity = EntitySearchResultView(
            neo4j_id="entity-123",
            similarity=0.92,
        )
        assert entity.neo4j_id == "entity-123"
        assert entity.similarity == 0.92


class TestVectorRepoIntegration:
    """Integration tests for VectorRepo with fallback databases."""

    @pytest.mark.asyncio
    async def test_vector_repo_initialization(self, relational_pool):
        """Test VectorRepo initializes correctly with real pool."""
        pool, db_type = relational_pool
        query_builder = create_vector_query_builder(db_type)
        repo = VectorRepo(pool, query_builder)
        assert repo._pool is pool

    @pytest.mark.asyncio
    async def test_upsert_article_vectors(self, relational_pool):
        """Test upsert_article_vectors creates vectors."""
        pool, db_type = relational_pool
        query_builder = create_vector_query_builder(db_type)
        vector_repo = VectorRepo(pool, query_builder)
        article_id = uuid.uuid4()

        # Create test article (split across base tables — `articles` is a VIEW)
        async with pool.session_context() as session:
            await session.execute(
                text("""INSERT INTO articles_core (id, source_url, title, is_merged)
                        VALUES (:id, :url, :title, :is_merged)"""),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{article_id}",
                    "title": "Test Article",
                    "is_merged": False,
                },
            )
            await session.execute(
                text(
                    """INSERT INTO article_bodies (article_id, body) VALUES (:article_id, :body)"""
                ),
                {"article_id": article_id, "body": "Test body content"},
            )
            await session.execute(
                text("""INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                        VALUES (:article_id, :is_news, :verified_by)"""),
                {"article_id": article_id, "is_news": True, "verified_by": 0},
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
            # Cleanup (cascades to article_bodies/article_analysis via FK)
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )

    @pytest.mark.asyncio
    async def test_find_similar(self, relational_pool):
        """Test find_similar returns similar articles."""
        pool, db_type = relational_pool
        query_builder = create_vector_query_builder(db_type)
        vector_repo = VectorRepo(pool, query_builder)
        article_id = uuid.uuid4()

        # Create test article (split across base tables — `articles` is a VIEW)
        async with pool.session_context() as session:
            await session.execute(
                text("""INSERT INTO articles_core (id, source_url, title, is_merged)
                        VALUES (:id, :url, :title, :is_merged)"""),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{article_id}",
                    "title": "Test Article",
                    "is_merged": False,
                },
            )
            await session.execute(
                text(
                    """INSERT INTO article_bodies (article_id, body) VALUES (:article_id, :body)"""
                ),
                {"article_id": article_id, "body": "Test body content"},
            )
            await session.execute(
                text("""INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                        VALUES (:article_id, :is_news, :verified_by)"""),
                {"article_id": article_id, "is_news": True, "verified_by": 0},
            )

        try:
            embedding = [0.1] * 1024

            await vector_repo.upsert_article_vectors(
                article_id=article_id,
                title_embedding=embedding,
                content_embedding=None,
                model_id="text-embedding-3-large",
            )

            results = await vector_repo.find_similar(
                embedding=embedding,
                limit=5,
            )
            assert isinstance(results, list)
        finally:
            # Cleanup (cascades to article_bodies/article_analysis via FK)
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
