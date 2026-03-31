# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for ArticleRepo - uses real PostgreSQL database."""

import uuid

import pytest
from sqlalchemy import text

from modules.pipeline.state import PipelineState
from modules.storage.article_repo import ArticleRepo


class TestArticleRepoIntegration:
    """Integration tests for ArticleRepo with real PostgreSQL."""

    @pytest.mark.asyncio
    async def test_article_repo_initialization(self, postgres_pool):
        """Test ArticleRepo initializes correctly with real pool."""
        repo = ArticleRepo(postgres_pool)
        assert repo._pool is postgres_pool

    @pytest.mark.asyncio
    async def test_upsert_creates_new_article(self, postgres_pool, unique_id):
        """Test upsert creates a new article when not exists."""
        repo = ArticleRepo(postgres_pool)

        state = PipelineState()
        state["raw"] = {
            "url": f"https://test.example.com/{unique_id}",
            "source_host": "test.example.com",
            "title": f"Test Article {unique_id}",
            "body": "Test body content",
            "publish_time": None,
        }
        state["is_news"] = True
        state["category"] = "tech"
        state["language"] = "zh"

        try:
            article_id = await repo.upsert(state)
            assert isinstance(article_id, uuid.UUID)

            # Verify article was created
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id, title, source_url FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row.title == f"Test Article {unique_id}"
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_article(self, postgres_pool, unique_id):
        """Test upsert updates existing article."""
        repo = ArticleRepo(postgres_pool)

        # First create an article
        state1 = PipelineState()
        state1["raw"] = {
            "url": f"https://test.example.com/{unique_id}",
            "source_host": "test.example.com",
            "title": f"Original Title {unique_id}",
            "body": "Original body",
            "publish_time": None,
        }
        state1["is_news"] = True

        try:
            article_id = await repo.upsert(state1)

            # Now update with same URL
            state2 = PipelineState()
            state2["raw"] = {
                "url": f"https://test.example.com/{unique_id}",
                "source_host": "test.example.com",
                "title": f"Updated Title {unique_id}",
                "body": "Updated body",
            }
            state2["is_news"] = True
            state2["cleaned"] = {"title": f"Updated Title {unique_id}", "body": "Updated body"}

            updated_id = await repo.upsert(state2)
            assert updated_id == article_id

            # Verify update
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT title FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.title == f"Updated Title {unique_id}"
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_get_article_by_id(self, postgres_pool, unique_id):
        """Test get article by UUID."""
        repo = ArticleRepo(postgres_pool)

        # Create test article
        async with postgres_pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, is_news, title, body, is_merged, verified_by_sources)
                    VALUES (:id, :url, :is_news, :title, :body, :is_merged, :verified_by)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "is_news": True,
                    "title": f"Test Article {unique_id}",
                    "body": "Test body",
                    "is_merged": False,
                    "verified_by": 0,
                },
            )

        try:
            result = await repo.get(article_id)
            assert result is not None
            assert result.id == article_id
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE id = :id"),
                    {"id": article_id},
                )

    @pytest.mark.asyncio
    async def test_get_article_by_string_id(self, postgres_pool, unique_id):
        """Test get article by string UUID."""
        repo = ArticleRepo(postgres_pool)

        # Create test article
        async with postgres_pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, is_news, title, body, is_merged, verified_by_sources)
                    VALUES (:id, :url, :is_news, :title, :body, :is_merged, :verified_by)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "is_news": True,
                    "title": f"Test Article {unique_id}",
                    "body": "Test body",
                    "is_merged": False,
                    "verified_by": 0,
                },
            )

        try:
            result = await repo.get(str(article_id))
            assert result is not None
            assert result.id == article_id
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE id = :id"),
                    {"id": article_id},
                )

    @pytest.mark.asyncio
    async def test_get_pending_neo4j(self, postgres_pool, unique_id):
        """Test get pending Neo4j articles."""
        repo = ArticleRepo(postgres_pool)

        # Create test article with persist_status pending
        async with postgres_pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, is_news, title, body, is_merged, verified_by_sources, persist_status)
                    VALUES (:id, :url, :is_news, :title, :body, :is_merged, :verified_by, 'pending_neo4j')
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "is_news": True,
                    "title": f"Test Article {unique_id}",
                    "body": "Test body",
                    "is_merged": False,
                    "verified_by": 0,
                },
            )

        try:
            result = await repo.get_pending_neo4j(limit=10)
            assert isinstance(result, list)
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_insert_raw_article(self, postgres_pool, unique_id):
        """Test insert raw article."""
        repo = ArticleRepo(postgres_pool)

        raw_article = {
            "url": f"https://test.example.com/{unique_id}",
            "source_host": "test.example.com",
            "title": f"Raw Article {unique_id}",
            "body": "Raw body",
        }

        try:
            article_id = await repo.insert_raw(raw_article)
            assert isinstance(article_id, uuid.UUID)

            # Verify article was created
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id FROM articles WHERE source_url = :url"),
                    {"url": raw_article["url"]},
                )
                row = result.fetchone()
                assert row is not None
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_insert_raw_existing_url(self, postgres_pool, unique_id):
        """Test insert raw article with existing URL returns existing id."""
        repo = ArticleRepo(postgres_pool)

        # First create an article
        raw1 = {
            "url": f"https://test.example.com/{unique_id}",
            "source_host": "test.example.com",
            "title": f"First Article {unique_id}",
            "body": "First body",
        }

        try:
            first_id = await repo.insert_raw(raw1)

            # Insert same URL again
            raw2 = {
                "url": f"https://test.example.com/{unique_id}",
                "source_host": "test.example.com",
                "title": f"Second Article {unique_id}",
                "body": "Second body",
            }
            second_id = await repo.insert_raw(raw2)

            # Should return same ID
            assert second_id == first_id
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_mark_failed(self, postgres_pool, unique_id):
        """Test mark article as failed."""
        repo = ArticleRepo(postgres_pool)

        # Create test article
        async with postgres_pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles (id, source_url, is_news, title, body, is_merged, verified_by_sources)
                    VALUES (:id, :url, :is_news, :title, :body, :is_merged, :verified_by)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "is_news": True,
                    "title": f"Test Article {unique_id}",
                    "body": "Test body",
                    "is_merged": False,
                    "verified_by": 0,
                },
            )

        try:
            await repo.mark_failed(article_id, "Test error")

            # Verify article was marked as failed
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT error FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.error == "Test error"
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
