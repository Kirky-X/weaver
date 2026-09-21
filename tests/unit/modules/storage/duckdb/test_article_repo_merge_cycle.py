# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Regression tests: DuckDBArticleRepo.detect_merge_cycle recursive CTE.

The merge-chain CTE previously used ``mc.path || a.id`` (UUID[] || UUID),
which DuckDB rejects with a Binder Error ("Cannot concatenate types UUID[]
and UUID - an explicit cast is required"). The query now uses
``array_append(mc.path, a.id)``, which both PostgreSQL and DuckDB support.

These tests run against a real in-memory DuckDB so the SQL is actually
compiled and executed (a mock pool cannot catch dialect regressions).
"""

import uuid

import pytest
from sqlalchemy import text

from core.db.duckdb_pool import DuckDBPool
from core.db.duckdb_schema import initialize_duckdb_schema
from modules.storage.duckdb.article_repo import DuckDBArticleRepo


@pytest.fixture
async def duckdb_repo():
    """In-memory DuckDB pool with schema initialized, wrapped in ArticleRepo."""
    pool = DuckDBPool(db_path=":memory:")
    await pool.startup()
    await initialize_duckdb_schema(pool)
    yield DuckDBArticleRepo(pool)
    await pool.shutdown()


async def _insert_core(pool, article_id: uuid.UUID, merged_into: uuid.UUID | None) -> None:
    """Insert a minimal articles_core row."""
    async with pool.session() as session:
        await session.execute(
            text(
                "INSERT INTO articles_core (id, source_url, merged_into) "
                "VALUES (:id, :url, :merged)"
            ),
            {"id": article_id, "url": f"https://example.com/{article_id}", "merged": merged_into},
        )
        await session.commit()


class TestDetectMergeCycleDuckDB:
    """detect_merge_cycle must execute on DuckDB without dialect errors."""

    async def test_no_cycle_returns_none(self, duckdb_repo):
        """A chain that never loops back returns None."""
        pool = duckdb_repo._pool
        a, b = uuid.uuid4(), uuid.uuid4()
        await _insert_core(pool, a, b)  # a -> b (terminal)
        await _insert_core(pool, b, None)

        result = await duckdb_repo.detect_merge_cycle(a, b)
        assert result is None

    async def test_cycle_detected_returns_cycle_path(self, duckdb_repo):
        """A merge loop a->b->c->a is detected and the cycle path returned."""
        pool = duckdb_repo._pool
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await _insert_core(pool, a, b)
        await _insert_core(pool, b, c)
        await _insert_core(pool, c, a)

        result = await duckdb_repo.detect_merge_cycle(c, a)
        assert result is not None
        # Cycle path revisits its starting node
        assert result[0] == result[-1]
        assert set(result[:-1]) == {a, b, c}

    async def test_article_id_inside_chain_detected(self, duckdb_repo):
        """article_id appearing anywhere in the merge chain is a cycle."""
        pool = duckdb_repo._pool
        a, b = uuid.uuid4(), uuid.uuid4()
        await _insert_core(pool, a, b)
        await _insert_core(pool, b, None)

        # Merging b into a closes the loop b->a->b (b is in a's merge chain)
        result = await duckdb_repo.detect_merge_cycle(b, a)
        assert result is not None
        assert b in result

    async def test_self_merge_returns_pair(self, duckdb_repo):
        """article_id == target_id short-circuits to a trivial cycle."""
        aid = uuid.uuid4()
        result = await duckdb_repo.detect_merge_cycle(aid, aid)
        assert result == [aid, aid]
