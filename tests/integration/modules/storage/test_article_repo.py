# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Integration tests for ArticleRepo - uses real database with automatic fallback.

Uses relational_pool fixture which automatically falls back to DuckDB
when PostgreSQL is unavailable.
"""

import uuid

import pytest
from sqlalchemy import text

from modules.processing.pipeline.state import PipelineState
from modules.storage import ArticleRepo


class TestArticleRepoIntegration:
    """Integration tests for ArticleRepo with real database.

    Uses relational_pool fixture which automatically falls back to DuckDB
    when PostgreSQL is unavailable.
    """

    @pytest.mark.asyncio
    async def test_article_repo_initialization(self, relational_pool):
        """Test ArticleRepo initializes correctly with real pool."""
        pool, _ = relational_pool
        repo = ArticleRepo(pool)
        assert repo._pool is pool

    @pytest.mark.asyncio
    async def test_upsert_creates_new_article(self, relational_pool, unique_id):
        """Test upsert creates a new article when not exists."""
        from types import SimpleNamespace

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        state = PipelineState()
        state["raw"] = SimpleNamespace(
            url=f"https://test.example.com/{unique_id}",
            source_host="test.example.com",
            title=f"Test Article {unique_id}",
            body="Test body content",
            publish_time=None,
        )
        state["is_news"] = True
        state["category"] = "科技"
        state["language"] = "zh"

        try:
            article_id = await repo.upsert(state)
            assert isinstance(article_id, uuid.UUID)

            # Verify article was created
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id, title, source_url FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row.title == f"Test Article {unique_id}"
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_article(self, relational_pool, unique_id):
        """Test upsert updates existing article with enriched fields."""
        from decimal import Decimal
        from types import SimpleNamespace

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # First create an article
        state1 = PipelineState()
        state1["raw"] = SimpleNamespace(
            url=f"https://test.example.com/{unique_id}",
            source_host="test.example.com",
            title=f"Original Title {unique_id}",
            body="Original body",
            publish_time=None,
        )
        state1["is_news"] = True

        try:
            article_id = await repo.upsert(state1)

            # Now update with enrichment fields
            state2 = PipelineState()
            state2["raw"] = SimpleNamespace(
                url=f"https://test.example.com/{unique_id}",
                source_host="test.example.com",
                title=f"Original Title {unique_id}",
                body="Original body",
                publish_time=None,
            )
            state2["is_news"] = True
            state2["score"] = Decimal("0.85")
            state2["quality_score"] = Decimal("0.90")

            updated_id = await repo.upsert(state2)
            assert updated_id == article_id

            # Verify update - enrichment fields should be set
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT score, quality_score FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.score == Decimal("0.85")
                assert row.quality_score == Decimal("0.90")
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_get_article_by_id(self, relational_pool, unique_id):
        """Test get article by UUID."""
        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # Create test article
        async with pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles_core (id, source_url, title, is_merged)
                    VALUES (:id, :url, :title, :is_merged)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "title": f"Test Article {unique_id}",
                    "is_merged": False,
                },
            )
            await session.execute(
                text("""
                    INSERT INTO article_bodies (article_id, body)
                    VALUES (:article_id, :body)
                """),
                {"article_id": article_id, "body": "Test body"},
            )
            await session.execute(
                text("""
                    INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                    VALUES (:article_id, :is_news, :verified_by)
                """),
                {"article_id": article_id, "is_news": True, "verified_by": 0},
            )

        try:
            result = await repo.get(article_id)
            assert result is not None
            assert result.id == article_id
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )

    @pytest.mark.asyncio
    async def test_get_article_by_string_id(self, relational_pool, unique_id):
        """Test get article by string UUID."""
        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # Create test article
        async with pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles_core (id, source_url, title, is_merged)
                    VALUES (:id, :url, :title, :is_merged)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "title": f"Test Article {unique_id}",
                    "is_merged": False,
                },
            )
            await session.execute(
                text("""
                    INSERT INTO article_bodies (article_id, body)
                    VALUES (:article_id, :body)
                """),
                {"article_id": article_id, "body": "Test body"},
            )
            await session.execute(
                text("""
                    INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                    VALUES (:article_id, :is_news, :verified_by)
                """),
                {"article_id": article_id, "is_news": True, "verified_by": 0},
            )

        try:
            result = await repo.get(str(article_id))
            assert result is not None
            assert result.id == article_id
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )

    @pytest.mark.asyncio
    async def test_get_pending_neo4j(self, relational_pool, unique_id):
        """Test get pending Neo4j articles."""
        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # Create test article with persist_status pg_done (what get_pending_neo4j queries)
        async with pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles_core (id, source_url, title, is_merged, persist_status)
                    VALUES (:id, :url, :title, :is_merged, 'pg_done')
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "title": f"Test Article {unique_id}",
                    "is_merged": False,
                },
            )
            await session.execute(
                text("""
                    INSERT INTO article_bodies (article_id, body)
                    VALUES (:article_id, :body)
                """),
                {"article_id": article_id, "body": "Test body"},
            )
            await session.execute(
                text("""
                    INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                    VALUES (:article_id, :is_news, :verified_by)
                """),
                {"article_id": article_id, "is_news": True, "verified_by": 0},
            )

        try:
            result = await repo.get_pending_neo4j(limit=10)
            assert isinstance(result, list)
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_insert_raw_article(self, relational_pool, unique_id):
        """Test insert raw article."""
        from modules.ingestion.domain.models import RawArticle

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        raw_article = RawArticle(
            url=f"https://test.example.com/{unique_id}",
            source_host="test.example.com",
            title=f"Raw Article {unique_id}",
            body="Raw body content for testing insert_raw",
        )

        try:
            article_id = await repo.insert_raw(raw_article)
            assert isinstance(article_id, uuid.UUID)

            # Verify article was created
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id FROM articles WHERE source_url = :url"),
                    {"url": raw_article.url},
                )
                row = result.fetchone()
                assert row is not None
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_insert_raw_existing_url(self, relational_pool, unique_id):
        """Test insert raw article with existing URL returns existing id."""
        from modules.ingestion.domain.models import RawArticle

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # First create an article
        raw1 = RawArticle(
            url=f"https://test.example.com/{unique_id}",
            source_host="test.example.com",
            title=f"First Article {unique_id}",
            body="First body content for testing duplicate detection",
        )

        try:
            first_id = await repo.insert_raw(raw1)

            # Insert same URL again
            raw2 = RawArticle(
                url=f"https://test.example.com/{unique_id}",
                source_host="test.example.com",
                title=f"Second Article {unique_id}",
                body="Second body content for testing duplicate detection",
            )
            second_id = await repo.insert_raw(raw2)

            # Should return same ID
            assert second_id == first_id
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE source_url LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_mark_failed(self, relational_pool, unique_id):
        """Test mark article as failed."""
        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # Create test article
        async with pool.session_context() as session:
            article_id = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO articles_core (id, source_url, title, is_merged)
                    VALUES (:id, :url, :title, :is_merged)
                """),
                {
                    "id": article_id,
                    "url": f"https://test.example.com/{unique_id}",
                    "title": f"Test Article {unique_id}",
                    "is_merged": False,
                },
            )
            await session.execute(
                text("""
                    INSERT INTO article_bodies (article_id, body)
                    VALUES (:article_id, :body)
                """),
                {"article_id": article_id, "body": "Test body"},
            )
            await session.execute(
                text("""
                    INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                    VALUES (:article_id, :is_news, :verified_by)
                """),
                {"article_id": article_id, "is_news": True, "verified_by": 0},
            )

        try:
            await repo.mark_failed(article_id, "Test error")

            # Verify article was marked as failed
            async with pool.session_context() as session:
                result = await session.execute(
                    text("SELECT processing_error FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.processing_error == "Test error"
        finally:
            # Cleanup
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )

    @pytest.mark.asyncio
    async def test_mark_terminal_by_url_inserts_new_article(self, relational_pool, unique_id):
        """Test mark_terminal_by_url handles new article (not exists in DB).

        Regression test for bug: terminal articles (is_news=False) were never
        inserted because mark_terminal_by_url only did UPDATE. New articles
        must be upserted so API queries can return them.

        Also verifies category value is valid for PostgreSQL ENUM constraint
        (category_type only allows: 政治/军事/经济/科技/社会/文化/体育/国际/其他).
        """
        from types import SimpleNamespace

        from modules.processing.pipeline.state import PipelineState

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        url = f"https://terminal-new.example.com/{unique_id}"

        # Simulate a terminal article state (is_news=False, no category)
        state = PipelineState()
        state["raw"] = SimpleNamespace(
            url=url,
            source_host="terminal-new.example.com",
            title=f"Non-news Page {unique_id}",
            body="Non-news content",
            publish_time=None,
        )
        state["is_news"] = False
        state["terminal"] = True

        try:
            # bulk_upsert should insert the terminal article
            article_ids = await repo.bulk_upsert([state])
            assert len(article_ids) == 1
            article_id = article_ids[0]

            # Verify article exists with PG_DONE status
            async with pool.session_context() as session:
                result = await session.execute(
                    text(
                        "SELECT id, title, persist_status, category FROM articles_core "
                        "WHERE source_url = :url"
                    ),
                    {"url": url},
                )
                row = result.fetchone()
                assert row is not None, "Terminal article must be inserted"
                assert row.title == f"Non-news Page {unique_id}"
                assert row.persist_status == "pg_done"
                # category can be NULL or valid enum value, never "other" (invalid)
                assert row.category != "other", "category='other' is invalid for PostgreSQL ENUM"
        finally:
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE source_url = :url"),
                    {"url": url},
                )

    @pytest.mark.asyncio
    async def test_mark_terminal_by_url_updates_existing_article(self, relational_pool, unique_id):
        """Test mark_terminal_by_url updates an existing PENDING article to PG_DONE.

        Regression test for bug: category='other' violated PostgreSQL ENUM.
        Verifies the update succeeds with a valid category value.
        """
        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        article_id = uuid.uuid4()
        url = f"https://terminal-existing.example.com/{unique_id}"

        # Insert a PENDING article first
        async with pool.session_context() as session:
            await session.execute(
                text("""
                    INSERT INTO articles_core (id, source_url, title, is_merged, persist_status)
                    VALUES (:id, :url, :title, false, 'pending')
                """),
                {
                    "id": article_id,
                    "url": url,
                    "title": f"Existing Terminal {unique_id}",
                },
            )
            await session.execute(
                text("""
                    INSERT INTO article_bodies (article_id, body)
                    VALUES (:article_id, :body)
                """),
                {"article_id": article_id, "body": "Body"},
            )
            await session.execute(
                text("""
                    INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                    VALUES (:article_id, false, 0)
                """),
                {"article_id": article_id},
            )

        try:
            # mark_terminal_by_url should NOT raise (was raising enum error)
            updated = await repo.mark_terminal_by_url(url)
            assert updated is True

            # Verify category is valid (not 'other')
            async with pool.session_context() as session:
                result = await session.execute(
                    text(
                        "SELECT persist_status, category FROM articles_core WHERE source_url = :url"
                    ),
                    {"url": url},
                )
                row = result.fetchone()
                assert row.persist_status == "pg_done"
                assert row.category != "other"
        finally:
            async with pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
