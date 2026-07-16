# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Integration tests for task progress statistics query.

Uses fallback databases (DuckDB) when PostgreSQL is not available.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from core.db import Article, PersistStatus


async def _insert_article_with_task(pool, article_id, url, title, body, persist_status, task_id):
    """Insert article into base tables (DuckDB doesn't support INSERT on VIEW).

    Inserts into articles_core, article_bodies, article_analysis, article_processing.
    """
    status_value = persist_status.value if hasattr(persist_status, "value") else persist_status
    async with pool.session() as session:
        await session.execute(
            text(
                "INSERT INTO articles_core (id, source_url, title, is_merged, persist_status) "
                "VALUES (:id, :url, :title, FALSE, :persist_status)"
            ),
            {
                "id": article_id,
                "url": url,
                "title": title,
                "persist_status": status_value,
            },
        )
        await session.execute(
            text("INSERT INTO article_bodies (article_id, body) " "VALUES (:article_id, :body)"),
            {"article_id": article_id, "body": body},
        )
        await session.execute(
            text(
                "INSERT INTO article_analysis (article_id, is_news, verified_by_sources) "
                "VALUES (:article_id, FALSE, 0)"
            ),
            {"article_id": article_id},
        )
        await session.execute(
            text(
                "INSERT INTO article_processing (article_id, task_id) "
                "VALUES (:article_id, :task_id)"
            ),
            {"article_id": article_id, "task_id": task_id},
        )
        await session.commit()


async def _delete_article_by_task_id(pool, task_id):
    """Delete articles by task_id from base tables in dependency order."""
    async with pool.session() as session:
        result = await session.execute(
            text("SELECT article_id FROM article_processing WHERE task_id = :task_id"),
            {"task_id": task_id},
        )
        article_ids = [row.article_id for row in result.fetchall()]

        for article_id in article_ids:
            await session.execute(
                text("DELETE FROM article_processing WHERE article_id = :article_id"),
                {"article_id": article_id},
            )
            await session.execute(
                text("DELETE FROM article_analysis WHERE article_id = :article_id"),
                {"article_id": article_id},
            )
            await session.execute(
                text("DELETE FROM article_bodies WHERE article_id = :article_id"),
                {"article_id": article_id},
            )
            await session.execute(
                text("DELETE FROM articles_core WHERE id = :article_id"),
                {"article_id": article_id},
            )
        await session.commit()


class TestTaskProgressStats:
    """Integration tests for get_task_progress_stats method."""

    @pytest.mark.asyncio
    async def test_get_progress_stats_returns_all_zeros_for_new_task(self, relational_pool):
        """Test that querying a task with no articles returns all zeros."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool, _ = relational_pool
        repo = ArticleRepo(pool)

        # Query stats for a task that doesn't exist
        stats = await repo.get_task_progress_stats(uuid.uuid4())

        assert stats["total_processed"] == 0
        assert stats["processing_count"] == 0
        assert stats["completed_count"] == 0
        assert stats["failed_count"] == 0
        assert stats["pending_count"] == 0

    @pytest.mark.asyncio
    async def test_get_progress_stats_with_mixed_statuses(self, relational_pool):
        """Test progress stats with articles in various persist statuses."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool, _ = relational_pool
        task_id = uuid.uuid4()

        # Create articles with different statuses for the same task
        statuses = [
            PersistStatus.PENDING,
            PersistStatus.PROCESSING,
            PersistStatus.PG_DONE,
            PersistStatus.NEO4J_DONE,
            PersistStatus.FAILED,
            PersistStatus.PENDING,
            PersistStatus.PROCESSING,
        ]

        try:
            for i, status in enumerate(statuses):
                await _insert_article_with_task(
                    pool,
                    article_id=uuid.uuid4(),
                    url=f"https://example.com/article_{uuid.uuid4().hex[:8]}",
                    title=f"Article {i}",
                    body="Content",
                    persist_status=status,
                    task_id=task_id,
                )

            repo = ArticleRepo(pool)
            stats = await repo.get_task_progress_stats(task_id)

            assert stats["total_processed"] == 7
            assert stats["pending_count"] == 2
            assert stats["processing_count"] == 2
            assert stats["completed_count"] == 2  # PG_DONE + NEO4J_DONE
            assert stats["failed_count"] == 1
        finally:
            # Cleanup
            await _delete_article_by_task_id(pool, task_id)

    @pytest.mark.asyncio
    async def test_get_progress_stats_excludes_other_tasks(self, relational_pool):
        """Test that stats only include articles for the specific task_id."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool, _ = relational_pool
        task_id_1 = uuid.uuid4()
        task_id_2 = uuid.uuid4()

        try:
            # Create articles for task 1
            for i in range(3):
                await _insert_article_with_task(
                    pool,
                    article_id=uuid.uuid4(),
                    url=f"https://example.com/task1_{uuid.uuid4().hex[:8]}",
                    title=f"Task1 Article {i}",
                    body="Content",
                    persist_status=PersistStatus.NEO4J_DONE,
                    task_id=task_id_1,
                )

            # Create articles for task 2
            for i in range(5):
                await _insert_article_with_task(
                    pool,
                    article_id=uuid.uuid4(),
                    url=f"https://example.com/task2_{uuid.uuid4().hex[:8]}",
                    title=f"Task2 Article {i}",
                    body="Content",
                    persist_status=PersistStatus.PENDING,
                    task_id=task_id_2,
                )

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
            await _delete_article_by_task_id(pool, task_id_1)
            await _delete_article_by_task_id(pool, task_id_2)

    @pytest.mark.asyncio
    async def test_get_progress_stats_excludes_null_task_id(self, relational_pool):
        """Test that articles with NULL task_id are excluded from stats."""
        from modules.storage.postgres.article_repo import ArticleRepo

        pool, _ = relational_pool
        task_id = uuid.uuid4()

        # Create article with the task_id
        with_task_url = f"https://example.com/with_task_{uuid.uuid4().hex[:8]}"
        without_task_urls = [
            f"https://example.com/without_task_{i}_{uuid.uuid4().hex[:8]}" for i in range(2)
        ]

        try:
            await _insert_article_with_task(
                pool,
                article_id=uuid.uuid4(),
                url=with_task_url,
                title="With Task",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE,
                task_id=task_id,
            )

            # Create articles without task_id (task_id=None)
            for i, url in enumerate(without_task_urls):
                await _insert_article_with_task(
                    pool,
                    article_id=uuid.uuid4(),
                    url=url,
                    title=f"Without Task {i}",
                    body="Content",
                    persist_status=(PersistStatus.NEO4J_DONE if i == 0 else PersistStatus.PENDING),
                    task_id=None,
                )

            repo = ArticleRepo(pool)
            stats = await repo.get_task_progress_stats(task_id)

            # Should only count the one article with the specific task_id
            assert stats["total_processed"] == 1
            assert stats["completed_count"] == 1
            assert stats["pending_count"] == 0
        finally:
            # Cleanup: delete by task_id, then by source_url pattern for null-task articles
            await _delete_article_by_task_id(pool, task_id)
            async with pool.session() as session:
                # Get article_ids matching the without_task URL pattern
                result = await session.execute(
                    text("SELECT id FROM articles_core WHERE source_url LIKE :pattern"),
                    {"pattern": "https://example.com/without_task_%"},
                )
                article_ids = [row.id for row in result.fetchall()]

                for article_id in article_ids:
                    await session.execute(
                        text("DELETE FROM article_processing WHERE article_id = :article_id"),
                        {"article_id": article_id},
                    )
                    await session.execute(
                        text("DELETE FROM article_analysis WHERE article_id = :article_id"),
                        {"article_id": article_id},
                    )
                    await session.execute(
                        text("DELETE FROM article_bodies WHERE article_id = :article_id"),
                        {"article_id": article_id},
                    )
                    await session.execute(
                        text("DELETE FROM articles_core WHERE id = :article_id"),
                        {"article_id": article_id},
                    )
                await session.commit()


class TestTaskCompletionDetermination:
    """Integration tests for task completion status logic."""

    @pytest.mark.asyncio
    async def test_task_completed_when_all_neo4j_done(self, relational_pool):
        """Test task is completed when all articles are COMPLETE."""
        pool, _ = relational_pool
        task_id = uuid.uuid4()

        try:
            for i in range(3):
                await _insert_article_with_task(
                    pool,
                    article_id=uuid.uuid4(),
                    url=f"https://example.com/done_{i}_{uuid.uuid4().hex[:8]}",
                    title=f"Done Article {i}",
                    body="Content",
                    persist_status=PersistStatus.NEO4J_DONE,
                    task_id=task_id,
                )

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
            await _delete_article_by_task_id(pool, task_id)

    @pytest.mark.asyncio
    async def test_task_not_completed_with_pending_articles(self, relational_pool):
        """Test task is NOT completed when articles are still pending."""
        pool, _ = relational_pool
        task_id = uuid.uuid4()

        try:
            await _insert_article_with_task(
                pool,
                article_id=uuid.uuid4(),
                url=f"https://example.com/done_{uuid.uuid4().hex[:8]}",
                title="Done",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE,
                task_id=task_id,
            )
            await _insert_article_with_task(
                pool,
                article_id=uuid.uuid4(),
                url=f"https://example.com/pending_{uuid.uuid4().hex[:8]}",
                title="Pending",
                body="Content",
                persist_status=PersistStatus.PENDING,
                task_id=task_id,
            )

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
            await _delete_article_by_task_id(pool, task_id)

    @pytest.mark.asyncio
    async def test_task_not_completed_with_processing_articles(self, relational_pool):
        """Test task is NOT completed when articles are in PROCESSING state."""
        pool, _ = relational_pool
        task_id = uuid.uuid4()

        try:
            await _insert_article_with_task(
                pool,
                article_id=uuid.uuid4(),
                url=f"https://example.com/processing_{uuid.uuid4().hex[:8]}",
                title="Processing",
                body="Content",
                persist_status=PersistStatus.PROCESSING,
                task_id=task_id,
            )

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
            await _delete_article_by_task_id(pool, task_id)

    @pytest.mark.asyncio
    async def test_task_completed_with_mixed_failed_and_done(self, relational_pool):
        """Test task is completed when remaining articles are all FAILED."""
        pool, _ = relational_pool
        task_id = uuid.uuid4()

        try:
            await _insert_article_with_task(
                pool,
                article_id=uuid.uuid4(),
                url=f"https://example.com/done_{uuid.uuid4().hex[:8]}",
                title="Done",
                body="Content",
                persist_status=PersistStatus.NEO4J_DONE,
                task_id=task_id,
            )
            await _insert_article_with_task(
                pool,
                article_id=uuid.uuid4(),
                url=f"https://example.com/failed_{uuid.uuid4().hex[:8]}",
                title="Failed",
                body="Content",
                persist_status=PersistStatus.FAILED,
                task_id=task_id,
            )

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
            await _delete_article_by_task_id(pool, task_id)

    @pytest.mark.asyncio
    async def test_task_completed_with_only_failed_articles(self, relational_pool):
        """Test task is completed when ALL articles are FAILED."""
        pool, _ = relational_pool
        task_id = uuid.uuid4()

        try:
            for i in range(2):
                await _insert_article_with_task(
                    pool,
                    article_id=uuid.uuid4(),
                    url=f"https://example.com/failed_{i}_{uuid.uuid4().hex[:8]}",
                    title=f"Failed {i}",
                    body="Content",
                    persist_status=PersistStatus.FAILED,
                    task_id=task_id,
                )

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
            await _delete_article_by_task_id(pool, task_id)
