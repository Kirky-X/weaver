# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T051 RED: DuckDBArticleRepo.fetch_bodies_by_pg_ids batch body lookup.

``DuckDBArticleRepo`` is currently an alias for ``ArticleRepo`` (see
``src/modules/storage/duckdb/article_repo.py``); both share the same ORM
implementation against ``ArticleBody``. This test guards the contract on
the DuckDB path so a future split keeps the same batch-lookup behavior.

See ``tests/unit/modules/storage/postgres/test_article_repo_fetch_bodies.py``
for the canonical contract tests; this file mirrors the high-value
scenarios on the DuckDB-bound class.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.duckdb.article_repo import DuckDBArticleRepo
from modules.storage.postgres.article_repo import ArticleRepo


def _make_body_row(pg_id, body):
    return (uuid.UUID(pg_id), body)


class TestDuckDBFetchBodiesByPgIds:
    """Mirror tests for DuckDBArticleRepo.fetch_bodies_by_pg_ids (T051)."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def article_repo(self, mock_pool):
        return DuckDBArticleRepo(mock_pool)

    def test_duckdb_repo_shares_article_repo_implementation(self):
        """Guard against silent drift: DuckDBArticleRepo must remain the
        ArticleRepo implementation so the shared ORM path covers DuckDB.

        Note: DuckDB's IN-clause semantics for large lists (plan-cache
        bloat, NULL handling) must be verified separately in integration
        tests, not here.
        """
        assert DuckDBArticleRepo is ArticleRepo

    @pytest.mark.asyncio
    async def test_empty_list_short_circuits(self, article_repo, mock_pool):
        result = await article_repo.fetch_bodies_by_pg_ids([])
        assert result == {}
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_matched_returns_full_mapping(self, article_repo, mock_pool):
        pg_id_1 = str(uuid.uuid4())
        pg_id_2 = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_body_row(pg_id_1, "Duck body one."),
                _make_body_row(pg_id_2, "Duck body two."),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_bodies_by_pg_ids([pg_id_1, pg_id_2])

        assert set(result.keys()) == {pg_id_1, pg_id_2}
        assert result[pg_id_1] == "Duck body one."
        assert result[pg_id_2] == "Duck body two."

    @pytest.mark.asyncio
    async def test_partial_match_returns_only_found(self, article_repo, mock_pool):
        pg_id_found = str(uuid.uuid4())
        pg_id_missing = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([_make_body_row(pg_id_found, "Found.")])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_bodies_by_pg_ids([pg_id_found, pg_id_missing])

        assert pg_id_found in result
        assert pg_id_missing not in result
        assert len(result) == 1
