# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for DuckDB fallback mode operations.

Verifies that DuckDB works correctly as a fallback database for
ArticleRepo operations. Uses in-memory DuckDB with schema initialization
— no external services required, no mocks.

These tests specifically exercise the DuckDB fallback path (not the
shared relational_pool fixture) to ensure the DuckDBPool, DuckDB schema,
and ArticleRepo work together in pure fallback mode.

Note: DuckDB uses a vertical split schema (articles_core + article_bodies +
article_analysis) with an ``articles`` VIEW for backward compatibility.
DuckDB does not support INSERT/DELETE on views, so test setup and cleanup
must operate directly on the base tables.
"""

import uuid

import pytest
from sqlalchemy import text

from core.db.duckdb_pool import DuckDBPool
from core.db.duckdb_schema import initialize_duckdb_schema
from modules.storage.duckdb.article_repo import DuckDBArticleRepo


@pytest.fixture
async def duckdb_pool():
    """Create an in-memory DuckDB pool with schema initialized.

    Uses :memory: mode for speed and isolation. All sessions share
    the same underlying connection so they see the same data.
    """
    pool = DuckDBPool(db_path=":memory:")
    await pool.startup()
    await initialize_duckdb_schema(pool)
    yield pool
    await pool.shutdown()


@pytest.fixture
def unique_id():
    """Generate unique test ID to avoid conflicts."""
    return str(uuid.uuid4())


async def _insert_article_direct(
    pool, article_id: uuid.UUID, url: str, title: str, body: str
) -> None:
    """Insert an article directly into DuckDB base tables.

    DuckDB does not support INSERT on the ``articles`` VIEW, so we
    insert into the three split tables manually.
    """
    async with pool.session_context() as session:
        await session.execute(
            text("""
                INSERT INTO articles_core (id, source_url, source_host, title, persist_status)
                VALUES (:id, :url, :host, :title, 'pending')
            """),
            {
                "id": article_id,
                "url": url,
                "host": url.split("//")[1].split("/")[0] if "//" in url else "",
                "title": title,
            },
        )
        await session.execute(
            text("""
                INSERT INTO article_bodies (article_id, body)
                VALUES (:id, :body)
            """),
            {"id": article_id, "body": body},
        )
        await session.execute(
            text("""
                INSERT INTO article_analysis (article_id, is_news, verified_by_sources)
                VALUES (:id, :is_news, :verified_by)
            """),
            {"id": article_id, "is_news": True, "verified_by": 0},
        )


async def _delete_article_direct(pool, article_id: uuid.UUID) -> None:
    """Delete an article from DuckDB base tables.

    DuckDB does not support DELETE on the ``articles`` VIEW, so we
    delete from the three split tables in reverse dependency order.
    """
    async with pool.session_context() as session:
        await session.execute(
            text("DELETE FROM article_analysis WHERE article_id = :id"),
            {"id": article_id},
        )
        await session.execute(
            text("DELETE FROM article_bodies WHERE article_id = :id"),
            {"id": article_id},
        )
        await session.execute(
            text("DELETE FROM articles_core WHERE id = :id"),
            {"id": article_id},
        )


async def _delete_articles_by_url_pattern(pool, pattern: str) -> None:
    """Delete articles matching a URL pattern from DuckDB base tables.

    Collects IDs from articles_core first, then deletes from all
    three split tables.
    """
    async with pool.session_context() as session:
        result = await session.execute(
            text("SELECT id FROM articles_core WHERE source_url LIKE :pattern"),
            {"pattern": pattern},
        )
        ids = [row[0] for row in result.fetchall()]

    for article_id in ids:
        await _delete_article_direct(pool, article_id)


class TestDuckDBPoolBasics:
    """Verify DuckDBPool implements RelationalPool protocol correctly."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_duckdb_pool_startup_shutdown(self):
        """Test DuckDBPool can start up and shut down cleanly."""
        pool = DuckDBPool(db_path=":memory:")
        await pool.startup()
        await pool.shutdown()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_duckdb_pool_session_context(self, duckdb_pool):
        """Test session_context yields a working session."""
        async with duckdb_pool.session_context() as session:
            result = await session.execute(text("SELECT 1 AS val"))
            row = result.fetchone()
            assert row.val == 1

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_duckdb_pool_session_as_context_manager(self, duckdb_pool):
        """Test pool.session() works as async context manager (used by ArticleRepo)."""
        async with duckdb_pool.session() as session:
            result = await session.execute(text("SELECT 42 AS val"))
            row = result.fetchone()
            assert row.val == 42


class TestDuckDBSchemaInitialization:
    """Verify DuckDB schema creates all required tables and views."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_articles_view_exists(self, duckdb_pool):
        """Test the articles VIEW (vertical split join) is created."""
        async with duckdb_pool.session_context() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'articles' AND table_type = 'VIEW'"
                )
            )
            count = result.scalar()
            assert count == 1

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_articles_core_table_exists(self, duckdb_pool):
        """Test articles_core table exists."""
        async with duckdb_pool.session_context() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'articles_core' AND table_type = 'BASE TABLE'"
                )
            )
            count = result.scalar()
            assert count == 1

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_article_bodies_table_exists(self, duckdb_pool):
        """Test article_bodies table exists."""
        async with duckdb_pool.session_context() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'article_bodies' AND table_type = 'BASE TABLE'"
                )
            )
            count = result.scalar()
            assert count == 1

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_article_analysis_table_exists(self, duckdb_pool):
        """Test article_analysis table exists."""
        async with duckdb_pool.session_context() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'article_analysis' AND table_type = 'BASE TABLE'"
                )
            )
            count = result.scalar()
            assert count == 1


class TestDuckDBArticleRepoQuery:
    """Test ArticleRepo query operations on DuckDB.

    Uses direct SQL inserts for setup since DuckDB does not support
    INSERT on the articles VIEW, and the ORM Article model maps to
    that VIEW.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_existing_urls(self, duckdb_pool, unique_id):
        """Test get_existing_urls returns matching URLs from DuckDB."""
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-urls.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"URL Test {unique_id}", "Body for URL check test"
        )

        try:
            existing = await repo.get_existing_urls([url])
            assert url in existing

            # Non-existent URL should not appear
            fake_url = f"https://nonexistent.example.com/{unique_id}"
            existing2 = await repo.get_existing_urls([fake_url])
            assert fake_url not in existing2
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_all_article_ids(self, duckdb_pool, unique_id):
        """Test get_all_article_ids returns IDs from DuckDB."""
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-ids.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"IDs Test {unique_id}", "Body for IDs test"
        )

        try:
            all_ids = await repo.get_all_article_ids()
            assert str(article_id) in all_ids
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_existing_urls_empty_list(self, duckdb_pool):
        """Test get_existing_urls returns empty set for empty input."""
        repo = DuckDBArticleRepo(duckdb_pool)
        result = await repo.get_existing_urls([])
        assert result == set()


class TestDuckDBArticleRepoStatusOperations:
    """Test ArticleRepo status management operations on DuckDB.

    These operations write to articles_core (base table) which works
    correctly with DuckDB.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mark_failed(self, duckdb_pool, unique_id):
        """Test mark_failed updates article status in DuckDB."""
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-fail.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"Fail Test {unique_id}", "Body for fail test"
        )

        try:
            await repo.mark_failed(article_id, "DuckDB test failure")

            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text(
                        "SELECT persist_status, processing_error FROM articles_core WHERE id = :id"
                    ),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.persist_status == "failed"
                assert row.processing_error == "DuckDB test failure"
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mark_processing(self, duckdb_pool, unique_id):
        """Test mark_processing updates article status in DuckDB."""
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-proc.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"Processing Test {unique_id}", "Body for processing test"
        )

        try:
            await repo.mark_processing(article_id, "nlp")

            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text(
                        "SELECT persist_status, processing_stage FROM articles_core WHERE id = :id"
                    ),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.persist_status == "processing"
                assert row.processing_stage == "nlp"
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_update_processing_stage(self, duckdb_pool, unique_id):
        """Test update_processing_stage in DuckDB."""
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-stage.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"Stage Test {unique_id}", "Body for stage test"
        )

        try:
            await repo.update_processing_stage(article_id, "vectorize")

            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT processing_stage FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
                stage = result.scalar()
                assert stage == "vectorize"
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_revert_to_pg_done(self, duckdb_pool, unique_id):
        """Test revert_to_pg_done reverts article status in DuckDB.

        Note: DuckDB's SQLAlchemy driver returns rowcount=-1 (unsupported),
        so revert_to_pg_done returns False even when the update succeeds.
        We verify the actual status change instead.
        """
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-revert.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"Revert Test {unique_id}", "Body for revert test"
        )

        try:
            # First mark as processing
            await repo.mark_processing(article_id, "nlp")

            # Then revert to pg_done (returns False due to DuckDB rowcount=-1)
            await repo.revert_to_pg_done(article_id)

            # Verify the actual status change
            async with duckdb_pool.session_context() as session:
                row_result = await session.execute(
                    text("SELECT persist_status FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
                status = row_result.scalar()
                assert status == "pg_done"
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mark_terminal_by_url(self, duckdb_pool, unique_id):
        """Test mark_terminal_by_url updates pending article to pg_done.

        Note: DuckDB's SQLAlchemy driver returns rowcount=-1 (unsupported),
        so mark_terminal_by_url returns False even when the update succeeds.
        We verify the actual status change instead.
        """
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-terminal.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"Terminal Test {unique_id}", "Body for terminal test"
        )

        try:
            await repo.mark_terminal_by_url(url)

            # Verify the actual status change
            async with duckdb_pool.session_context() as session:
                row_result = await session.execute(
                    text("SELECT persist_status FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
                status = row_result.scalar()
                assert status == "pg_done"
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_bulk_update_processing_stage(self, duckdb_pool, unique_id):
        """Test bulk_update_processing_stage updates multiple articles."""
        repo = DuckDBArticleRepo(duckdb_pool)

        ids = [uuid.uuid4() for _ in range(3)]
        for aid in ids:
            url = f"https://duckdb-bulk.example.com/{unique_id}/{aid}"
            await _insert_article_direct(
                duckdb_pool, aid, url, f"Bulk Test {aid}", "Body for bulk test"
            )

        try:
            await repo.bulk_update_processing_stage(ids, "embedding")

            for aid in ids:
                async with duckdb_pool.session_context() as session:
                    result = await session.execute(
                        text("SELECT processing_stage FROM articles_core WHERE id = :id"),
                        {"id": aid},
                    )
                    assert result.scalar() == "embedding"
        finally:
            for aid in ids:
                await _delete_article_direct(duckdb_pool, aid)


class TestDuckDBArticleRepoEnrichment:
    """Test ArticleRepo enrichment operations on DuckDB.

    These operations write to specific split tables (articles_core,
    article_bodies, article_analysis) which work correctly with DuckDB.
    """

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_update_enrichment_if_null(self, duckdb_pool, unique_id):
        """Test update_enrichment_if_null sets NULL fields in DuckDB."""
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-enrich.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"Enrich Test {unique_id}", "Body for enrichment test"
        )

        try:
            updated = await repo.update_enrichment_if_null(
                article_id,
                category="科技",
                score=0.85,
                summary="Test summary",
                quality_score=0.90,
            )
            assert updated is True

            # Verify category and score on articles_core
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT category, score FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.category == "科技"
                assert float(row.score) == pytest.approx(0.85)

            # Verify summary on article_bodies
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT summary FROM article_bodies WHERE article_id = :id"),
                    {"id": article_id},
                )
                summary = result.scalar()
                assert summary == "Test summary"

            # Verify quality_score on article_analysis
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT quality_score FROM article_analysis WHERE article_id = :id"),
                    {"id": article_id},
                )
                quality = result.scalar()
                assert float(quality) == pytest.approx(0.90)

            # Second call should be idempotent (fields no longer NULL)
            updated2 = await repo.update_enrichment_if_null(
                article_id,
                category="财经",
                score=0.50,
            )
            assert updated2 is False

            # Values should remain unchanged
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT category, score FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row.category == "科技"
                assert float(row.score) == pytest.approx(0.85)
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_update_credibility(self, duckdb_pool, unique_id):
        """Test update_credibility updates split tables in DuckDB."""
        repo = DuckDBArticleRepo(duckdb_pool)

        article_id = uuid.uuid4()
        url = f"https://duckdb-cred.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool,
            article_id,
            url,
            f"Credibility Test {unique_id}",
            "Body for credibility test",
        )

        try:
            await repo.update_credibility(
                article_id,
                credibility_score=0.75,
                cross_verification=0.80,
                verified_by_sources=3,
            )

            # Verify credibility_score on articles_core
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT credibility_score FROM articles_core WHERE id = :id"),
                    {"id": article_id},
                )
                score = result.scalar()
                assert float(score) == pytest.approx(0.75)

            # Verify cross_verification and verified_by_sources on article_analysis
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text(
                        "SELECT cross_verification, verified_by_sources FROM article_analysis WHERE article_id = :id"
                    ),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert float(row.cross_verification) == pytest.approx(0.80)
                assert row.verified_by_sources == 3
        finally:
            await _delete_article_direct(duckdb_pool, article_id)


class TestDuckDBVerticalSplitConsistency:
    """Test that the articles VIEW correctly joins the vertical split tables."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_view_joins_core_body_analysis(self, duckdb_pool, unique_id):
        """Test base tables join correctly across all three split tables."""
        article_id = uuid.uuid4()
        url = f"https://duckdb-view.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool,
            article_id,
            url,
            f"View Join Test {unique_id}",
            "Body content for view join verification",
        )

        try:
            # Add analysis data via SQL
            async with duckdb_pool.session_context() as session:
                await session.execute(
                    text("""
                        UPDATE article_analysis
                        SET is_news = true, quality_score = 0.88
                        WHERE article_id = :id
                    """),
                    {"id": article_id},
                )

            # Query through the base tables directly
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("""
                        SELECT c.title, b.body, a.is_news, a.quality_score
                        FROM articles_core c
                        JOIN article_bodies b ON c.id = b.article_id
                        JOIN article_analysis a ON c.id = a.article_id
                        WHERE c.id = :id
                    """),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row.title == f"View Join Test {unique_id}"
                assert row.body == "Body content for view join verification"
                assert row.is_news is True
                assert float(row.quality_score) == pytest.approx(0.88)
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_articles_view_readable_without_analysis(self, duckdb_pool, unique_id):
        """Test articles VIEW returns rows even when article_analysis is missing."""
        article_id = uuid.uuid4()
        async with duckdb_pool.session_context() as session:
            # Insert only core + body (no analysis row)
            await session.execute(
                text("""
                    INSERT INTO articles_core (id, source_url, source_host, title)
                    VALUES (:id, :url, :host, :title)
                """),
                {
                    "id": article_id,
                    "url": f"https://duckdb-noanalysis.example.com/{unique_id}",
                    "host": "duckdb-noanalysis.example.com",
                    "title": f"No Analysis {unique_id}",
                },
            )
            await session.execute(
                text("""
                    INSERT INTO article_bodies (article_id, body)
                    VALUES (:id, :body)
                """),
                {"id": article_id, "body": "Body without analysis"},
            )

        try:
            # VIEW should still return the row (LEFT JOIN)
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT title, body, is_news FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row.title == f"No Analysis {unique_id}"
                assert row.body == "Body without analysis"
                assert row.is_news is None  # LEFT JOIN, no analysis row
        finally:
            await _delete_article_direct(duckdb_pool, article_id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_articles_view_select_core_fields(self, duckdb_pool, unique_id):
        """Test articles VIEW correctly exposes core fields."""
        article_id = uuid.uuid4()
        url = f"https://duckdb-viewcore.example.com/{unique_id}"
        await _insert_article_direct(
            duckdb_pool, article_id, url, f"View Core Test {unique_id}", "Body for view core test"
        )

        try:
            # Query core fields through the VIEW
            async with duckdb_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id, source_url, title, body FROM articles WHERE id = :id"),
                    {"id": article_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row.id == article_id
                assert row.source_url == url
                assert row.title == f"View Core Test {unique_id}"
                assert row.body == "Body for view core test"
        finally:
            await _delete_article_direct(duckdb_pool, article_id)
