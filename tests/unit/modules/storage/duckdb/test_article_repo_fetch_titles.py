# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T023 RED: DuckDBArticleRepo.fetch_titles_by_pg_ids batch metadata lookup.

``DuckDBArticleRepo`` is currently an alias for ``ArticleRepo`` (see
``src/modules/storage/duckdb/article_repo.py``); both share the same ORM
implementation against ``ArticleCore``. This test guards the contract on
the DuckDB path so that a future split of the DuckDB implementation
keeps providing the same batch-lookup behavior.

Scope note: this file only verifies identity + high-level contract
scenarios. It does NOT verify DuckDB-specific IN-clause semantics
(plan-cache behavior, NULL handling, large-list parsing) — those
belong in integration tests against a real DuckDB instance.

See ``tests/unit/modules/storage/postgres/test_article_repo_fetch_titles.py``
for the canonical contract tests; this file mirrors the high-value
scenarios on the DuckDB-bound class.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.duckdb.article_repo import DuckDBArticleRepo
from modules.storage.postgres.article_repo import ArticleRepo


def _make_row(pg_id, title, category, publish_time, score):
    return (uuid.UUID(pg_id), title, category, publish_time, score)


class TestDuckDBFetchTitlesByPgIds:
    """Mirror tests for DuckDBArticleRepo.fetch_titles_by_pg_ids (T023)."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def article_repo(self, mock_pool):
        return DuckDBArticleRepo(mock_pool)

    def test_duckdb_repo_shares_article_repo_implementation(self):
        """Guard against silent drift: DuckDBArticleRepo must remain the
        ArticleRepo implementation so the shared ORM path covers DuckDB.

        Note: This guard accepts the alias as a design decision. DuckDB's
        IN-clause semantics for large lists (plan-cache bloat, NULL
        handling) must be verified separately in integration tests, not
        here — this unit test only locks the identity contract.

        Future note: if DuckDBArticleRepo is ever split into an
        independent implementation, delete this guard and add a
        DuckDB-specific ``fetch_titles_by_pg_ids`` test that exercises
        DuckDB's IN-clause semantics directly.
        """
        assert DuckDBArticleRepo is ArticleRepo

    @pytest.mark.asyncio
    async def test_empty_list_short_circuits(self, article_repo, mock_pool):
        result = await article_repo.fetch_titles_by_pg_ids([])
        assert result == {}
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_matched_returns_full_mapping(self, article_repo, mock_pool):
        pg_id_1 = str(uuid.uuid4())
        pg_id_2 = str(uuid.uuid4())
        publish_time = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_row(pg_id_1, "Duck Article One", "tech", publish_time, 0.9),
                _make_row(pg_id_2, "Duck Article Two", "finance", None, 0.4),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_titles_by_pg_ids([pg_id_1, pg_id_2])

        assert set(result.keys()) == {pg_id_1, pg_id_2}
        assert result[pg_id_1]["title"] == "Duck Article One"
        assert result[pg_id_1]["publish_time"] == publish_time
        assert result[pg_id_2]["publish_time"] is None
        assert result[pg_id_2]["score"] == 0.4

    @pytest.mark.asyncio
    async def test_partial_match_returns_only_found(self, article_repo, mock_pool):
        pg_id_found = str(uuid.uuid4())
        pg_id_missing = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_row(pg_id_found, "Found", "tech", None, None),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_titles_by_pg_ids([pg_id_found, pg_id_missing])

        assert pg_id_found in result
        assert pg_id_missing not in result
        assert len(result) == 1
