# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for DuckDB schema VIEW_QUERIES — verifies each view can be created
and queried in an in-memory DuckDB.

Covers R-duckdb-schema-003 (view completeness). Unlike regex-based tests in
test_duckdb_schema_completeness.py, this file actually executes VIEW_QUERIES
against a real in-memory DuckDB to catch SQL syntax errors and DuckDB-
incompatible view definitions.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from core.db.duckdb_schema import VIEW_QUERIES


@pytest.fixture
async def in_memory_duckdb_with_views():
    """In-memory DuckDB pool with schema (tables + sequences + views) initialized."""
    from core.db.duckdb_pool import DuckDBPool
    from core.db.duckdb_schema import initialize_duckdb_schema

    pool = DuckDBPool(db_path=":memory:")
    await pool.startup()
    try:
        await initialize_duckdb_schema(pool)
        yield pool
    finally:
        await pool.shutdown()


def _parse_view_name(view_query: str) -> str | None:
    """Extract view name from CREATE VIEW IF NOT EXISTS <name> AS ..."""
    import re

    match = re.search(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
        view_query,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


class TestDuckDBSchemaViews:
    """Verify VIEW_QUERIES creates views that are SELECTable in in-memory DuckDB."""

    @pytest.mark.parametrize(
        "view_query",
        VIEW_QUERIES,
        ids=[_parse_view_name(q) or f"view_{i}" for i, q in enumerate(VIEW_QUERIES)],
    )
    @pytest.mark.asyncio
    async def test_view_selectable_in_memory(self, view_query, in_memory_duckdb_with_views):
        """Each view must be created and SELECTable in in-memory DuckDB."""
        view_name = _parse_view_name(view_query)
        assert view_name, f"Cannot parse view name from: {view_query}"

        async with in_memory_duckdb_with_views.session() as session:
            result = await session.execute(
                text(f'SELECT * FROM "{view_name}" LIMIT 0')  # noqa: S608 (constant list)
            )
            # Should not raise; result.fetchall() returns []
            assert result.fetchall() == []

    @pytest.mark.asyncio
    async def test_all_views_present_in_information_schema(self, in_memory_duckdb_with_views):
        """All views in VIEW_QUERIES must appear in information_schema.views."""
        expected_view_names = {_parse_view_name(q) for q in VIEW_QUERIES if _parse_view_name(q)}
        assert expected_view_names, "No view names parsed from VIEW_QUERIES"

        async with in_memory_duckdb_with_views.session() as session:
            result = await session.execute(
                text("SELECT table_name FROM information_schema.views WHERE table_schema = 'main'")
            )
            actual_views = {row[0] for row in result.fetchall()}

        missing = expected_view_names - actual_views
        assert not missing, f"Missing views in DuckDB schema: {sorted(missing)}"

    @pytest.mark.asyncio
    async def test_articles_view_returns_columns_from_four_tables(
        self, in_memory_duckdb_with_views
    ):
        """The articles VIEW must join articles_core + article_bodies + article_analysis + article_processing."""
        async with in_memory_duckdb_with_views.session() as session:
            result = await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'articles' ORDER BY ordinal_position"
                )
            )
            columns = {row[0] for row in result.fetchall()}

        # Verify columns from all four underlying tables are present
        # articles_core: id, source_url, title (among others)
        assert "id" in columns, "articles view missing 'id' from articles_core"
        assert "source_url" in columns, "articles view missing 'source_url' from articles_core"
        assert "title" in columns, "articles view missing 'title' from articles_core"
        # article_bodies: body, summary
        assert "body" in columns, "articles view missing 'body' from article_bodies"
        assert "summary" in columns, "articles view missing 'summary' from article_bodies"
        # article_analysis: is_news, sentiment
        assert "is_news" in columns, "articles view missing 'is_news' from article_analysis"
        assert "sentiment" in columns, "articles view missing 'sentiment' from article_analysis"
        # article_processing: task_id, processing_stage
        assert "task_id" in columns, "articles view missing 'task_id' from article_processing"
        assert (
            "processing_stage" in columns
        ), "articles view missing 'processing_stage' from article_processing"

    @pytest.mark.asyncio
    async def test_articles_view_query_with_limit_returns_empty(self, in_memory_duckdb_with_views):
        """SELECT FROM articles view must work even with empty tables."""
        async with in_memory_duckdb_with_views.session() as session:
            result = await session.execute(text("SELECT * FROM articles LIMIT 10"))
            rows = result.fetchall()
            # Empty tables → empty result
            assert rows == []
