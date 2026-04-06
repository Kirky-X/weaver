# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for task progress statistics query."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select

from core.db.models import Article, PersistStatus


def get_test_pool():
    """Create a new PostgresPool for testing."""
    from core.db.postgres import PostgresPool

    # Use WEAVER_POSTGRES__DSN if set (Docker Compose), otherwise fallback to localhost:5432
    dsn = os.getenv(
        "WEAVER_POSTGRES__DSN",
        os.getenv(
            "POSTGRES_DSN",
            f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:{os.getenv('POSTGRES_PASSWORD', 'invalid')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DATABASE', 'weaver')}",
        ),
    )
    return PostgresPool(dsn)


async def _check_postgres_available() -> bool:
    """Check if PostgreSQL is available."""
    try:
        pool = get_test_pool()
        await pool.startup()
        await pool.shutdown()
        return True
    except Exception:
        return False


@pytest.fixture
async def skip_if_no_postgres():
    """Skip test if PostgreSQL is not available."""
    if not await _check_postgres_available():
        pytest.skip("PostgreSQL not available")


class TestTaskProgressStats:
    """Integration tests for get_task_progress_stats method."""

    @pytest.mark.asyncio
    async def test_get_progress_stats_returns_all_zeros_for_new_task(self, skip_if_no_postgres):
        """Test that querying a task with no articles returns all zeros."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool = get_test_pool()
        await pool.startup()
        try:
            repo = ArticleRepo(pool)

            # Query stats for a task that doesn't exist
            stats = await repo.get_task_progress_stats(uuid.uuid4())

            assert stats["total_processed"] == 0
            assert stats["processing_count"] == 0
            assert stats["completed_count"] == 0
            assert stats["failed_count"] == 0
            assert stats["pending_count"] == 0
        finally:
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_get_progress_stats_with_mixed_statuses(self, skip_if_no_postgres):
        """Test progress stats with articles in various persist statuses."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool = get_test_pool()
        await pool.startup()

        task_id = uuid.uuid4()

        # Create articles with different statuses for the same task
        articles = [
            Article(
                source_url=f"https://example.com/article_{uuid.uuid4().hex[:8]}",
                title=f"Article {i}",
                body="Content",
                persist_status=status,
                task_id=task_id,
            )
            for i, status in enumerate(
                [
                    PersistStatus.PENDING,
                    PersistStatus.PROCESSING,
                    PersistStatus.PG_DONE,
                    PersistStatus.NEO4J_DONE,
                    PersistStatus.FAILED,
                    PersistStatus.PENDING,
                    PersistStatus.PROCESSING,
                ]
            )
        ]

        try:
            async with pool.session() as session:
                session.add_all(articles)
                await session.commit()

            repo = ArticleRepo(pool)
            stats = await repo.get_task_progress_stats(task_id)

            assert stats["total_processed"] == 7
            assert stats["pending_count"] == 2
            assert stats["processing_count"] == 2
            assert stats["completed_count"] == 2  # PG_DONE + NEO4J_DONE
            assert stats["failed_count"] == 1
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id))
                await session.commit()
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_get_progress_stats_excludes_other_tasks(self, skip_if_no_postgres):
        """Test that stats only include articles for the specific task_id."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool = get_test_pool()
        await pool.startup()

        task_id_1 = uuid.uuid4()
        task_id_2 = uuid.uuid4()

        # Create articles for task 1
        articles_t1 = [
            Article(
                source_url=f"https://example.com/task1_{uuid.uuid4().hex[:8]}",
                title=f"Task1 Article {i}",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE,
                task_id=task_id_1,
            )
            for i in range(3)
        ]

        # Create articles for task 2
        articles_t2 = [
            Article(
                source_url=f"https://example.com/task2_{uuid.uuid4().hex[:8]}",
                title=f"Task2 Article {i}",
                body="Content",
                persist_status=PersistStatus.PENDING,
                task_id=task_id_2,
            )
            for i in range(5)
        ]

        try:
            async with pool.session() as session:
                session.add_all(articles_t1 + articles_t2)
                await session.commit()

            repo = ArticleRepo(pool)

            stats1 = await repo.get_task_progress_stats(task_id_1)
            stats2 = await repo.get_task_progress_stats(task_id_2)

            assert stats1["total_processed"] == 3
            assert stats1["completed_count"] == 3
            assert stats1["pending_count"] == 0

            assert stats2["total_processed"] == 5
            assert stats2["completed_count"] == 0
            assert stats2["pending_count"] == 5
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id_1))
                await session.execute(delete(Article).where(Article.task_id == task_id_2))
                await session.commit()
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_get_progress_stats_excludes_null_task_id(self, skip_if_no_postgres):
        """Test that articles with NULL task_id are excluded from stats."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool = get_test_pool()
        await pool.startup()

        task_id = uuid.uuid4()

        # Create article with the task_id
        article_with_task = Article(
            source_url=f"https://example.com/with_task_{uuid.uuid4().hex[:8]}",
            title="With Task",
            body="Content",
            persist_status=PersistStatus.NEO4J_DONE,
            task_id=task_id,
        )

        # Create articles without task_id (backward compatibility)
        articles_without_task = [
            Article(
                source_url=f"https://example.com/without_task_{i}_{uuid.uuid4().hex[:8]}",
                title=f"Without Task {i}",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE if i == 0 else PersistStatus.PENDING,
                # task_id is None by default
            )
            for i in range(2)
        ]

        try:
            async with pool.session() as session:
                session.add(article_with_task)
                session.add_all(articles_without_task)
                await session.commit()

            repo = ArticleRepo(pool)
            stats = await repo.get_task_progress_stats(task_id)

            # Should only count the one article with the specific task_id
            assert stats["total_processed"] == 1
            assert stats["completed_count"] == 1
            assert stats["pending_count"] == 0
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id))
                await session.execute(
                    delete(Article).where(
                        Article.source_url.like("https://example.com/without_task_%")
                    )
                )
                await session.commit()
            await pool.shutdown()


class TestTaskCompletionDetermination:
    """Integration tests for task completion status logic."""

    @pytest.mark.asyncio
    async def test_task_completed_when_all_neo4j_done(self, skip_if_no_postgres):
        """Test task is completed when all articles are NEO4J_DONE."""
        pool = get_test_pool()
        await pool.startup()

        task_id = uuid.uuid4()

        articles = [
            Article(
                source_url=f"https://example.com/done_{i}_{uuid.uuid4().hex[:8]}",
                title=f"Done Article {i}",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE,
                task_id=task_id,
            )
            for i in range(3)
        ]

        try:
            async with pool.session() as session:
                session.add_all(articles)
                await session.commit()

            # Check: task is completed if no articles in non-terminal states
            async with pool.session() as session:
                result = await session.execute(
                    select(Article).where(
                        Article.task_id == task_id,
                        Article.persist_status.notin_(
                            [PersistStatus.NEO4J_DONE, PersistStatus.FAILED]
                        ),
                    )
                )
                pending = result.scalars().all()

            is_completed = len(pending) == 0

            assert is_completed is True
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id))
                await session.commit()
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_task_not_completed_with_pending_articles(self, skip_if_no_postgres):
        """Test task is NOT completed when articles are still pending."""
        pool = get_test_pool()
        await pool.startup()

        task_id = uuid.uuid4()

        articles = [
            Article(
                source_url=f"https://example.com/done_{uuid.uuid4().hex[:8]}",
                title="Done",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE,
                task_id=task_id,
            ),
            Article(
                source_url=f"https://example.com/pending_{uuid.uuid4().hex[:8]}",
                title="Pending",
                body="Content",
                persist_status=PersistStatus.PENDING,
                task_id=task_id,
            ),
        ]

        try:
            async with pool.session() as session:
                session.add_all(articles)
                await session.commit()

            async with pool.session() as session:
                result = await session.execute(
                    select(Article).where(
                        Article.task_id == task_id,
                        Article.persist_status.notin_(
                            [PersistStatus.NEO4J_DONE, PersistStatus.FAILED]
                        ),
                    )
                )
                pending = result.scalars().all()

            is_completed = len(pending) == 0

            assert is_completed is False
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id))
                await session.commit()
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_task_not_completed_with_processing_articles(self, skip_if_no_postgres):
        """Test task is NOT completed when articles are in PROCESSING state."""
        pool = get_test_pool()
        await pool.startup()

        task_id = uuid.uuid4()

        article = Article(
            source_url=f"https://example.com/processing_{uuid.uuid4().hex[:8]}",
            title="Processing",
            body="Content",
            persist_status=PersistStatus.PROCESSING,
            task_id=task_id,
        )

        try:
            async with pool.session() as session:
                session.add(article)
                await session.commit()

            async with pool.session() as session:
                result = await session.execute(
                    select(Article).where(
                        Article.task_id == task_id,
                        Article.persist_status.notin_(
                            [PersistStatus.NEO4J_DONE, PersistStatus.FAILED]
                        ),
                    )
                )
                pending = result.scalars().all()

            is_completed = len(pending) == 0

            assert is_completed is False
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id))
                await session.commit()
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_task_completed_with_mixed_failed_and_done(self, skip_if_no_postgres):
        """Test task is completed when remaining articles are all FAILED."""
        pool = get_test_pool()
        await pool.startup()

        task_id = uuid.uuid4()

        articles = [
            Article(
                source_url=f"https://example.com/done_{uuid.uuid4().hex[:8]}",
                title="Done",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE,
                task_id=task_id,
            ),
            Article(
                source_url=f"https://example.com/failed_{uuid.uuid4().hex[:8]}",
                title="Failed",
                body="Content",
                persist_status=PersistStatus.FAILED,
                task_id=task_id,
            ),
        ]

        try:
            async with pool.session() as session:
                session.add_all(articles)
                await session.commit()

            async with pool.session() as session:
                result = await session.execute(
                    select(Article).where(
                        Article.task_id == task_id,
                        Article.persist_status.notin_(
                            [PersistStatus.NEO4J_DONE, PersistStatus.FAILED]
                        ),
                    )
                )
                pending = result.scalars().all()

            is_completed = len(pending) == 0

            assert is_completed is True
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id))
                await session.commit()
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_task_completed_with_only_failed_articles(self, skip_if_no_postgres):
        """Test task is completed when ALL articles are FAILED."""
        pool = get_test_pool()
        await pool.startup()

        task_id = uuid.uuid4()

        articles = [
            Article(
                source_url=f"https://example.com/failed_{i}_{uuid.uuid4().hex[:8]}",
                title=f"Failed {i}",
                body="Content",
                persist_status=PersistStatus.FAILED,
                task_id=task_id,
            )
            for i in range(2)
        ]

        try:
            async with pool.session() as session:
                session.add_all(articles)
                await session.commit()

            async with pool.session() as session:
                result = await session.execute(
                    select(Article).where(
                        Article.task_id == task_id,
                        Article.persist_status.notin_(
                            [PersistStatus.NEO4J_DONE, PersistStatus.FAILED]
                        ),
                    )
                )
                pending = result.scalars().all()

            is_completed = len(pending) == 0

            assert is_completed is True
        finally:
            # Cleanup
            async with pool.session() as session:
                await session.execute(delete(Article).where(Article.task_id == task_id))
                await session.commit()
            await pool.shutdown()
