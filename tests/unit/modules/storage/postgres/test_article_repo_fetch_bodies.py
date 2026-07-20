# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T051 RED: ArticleRepo.fetch_bodies_by_pg_ids batch body lookup.

Mirrors the contract of ``fetch_titles_by_pg_ids`` but for article body
content. Used by ``ContextBuilder.fetch_article_bodies`` to replace the
N+1 per-id ``repo.get`` loop with a single batched SELECT.

Contract:
    Input:  ``pg_ids: list[str]`` (UUID strings, may be empty)
    Output: ``dict[str, str]`` mapping ``pg_id`` -> body text. Missing
            IDs are omitted from the result (not empty string).
    Edge:
        - Empty input -> empty dict (no DB hit)
        - Partial match -> only matched entries returned
        - Invalid UUID -> skipped with warning log (not raised)
        - Large batch (>=500) -> chunked queries
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.postgres.article_repo import ArticleRepo


def _make_body_row(pg_id: str, body: str) -> tuple:
    """Build a fake result row matching the SELECT column order."""
    return (uuid.UUID(pg_id), body)


class TestFetchBodiesByPgIds:
    """Tests for ArticleRepo.fetch_bodies_by_pg_ids (T051)."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def article_repo(self, mock_pool):
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_dict_without_db_hit(self, article_repo, mock_pool):
        """Empty pg_ids list short-circuits without opening a session."""
        result = await article_repo.fetch_bodies_by_pg_ids([])

        assert result == {}
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_matched_returns_full_mapping(self, article_repo, mock_pool):
        """When every pg_id matches, return a mapping of pg_id -> body."""
        pg_id_1 = str(uuid.uuid4())
        pg_id_2 = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_body_row(pg_id_1, "Body of article one."),
                _make_body_row(pg_id_2, "Body of article two."),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_bodies_by_pg_ids([pg_id_1, pg_id_2])

        assert set(result.keys()) == {pg_id_1, pg_id_2}
        assert result[pg_id_1] == "Body of article one."
        assert result[pg_id_2] == "Body of article two."

    @pytest.mark.asyncio
    async def test_partial_match_returns_only_found(self, article_repo, mock_pool):
        """When only some pg_ids exist, return only the matched subset."""
        pg_id_found = str(uuid.uuid4())
        pg_id_missing = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([_make_body_row(pg_id_found, "Found body.")])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_bodies_by_pg_ids([pg_id_found, pg_id_missing])

        assert pg_id_found in result
        assert pg_id_missing not in result
        assert len(result) == 1
        assert result[pg_id_found] == "Found body."

    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_dict(self, article_repo, mock_pool):
        """When no pg_ids match, return an empty dict (not None values)."""
        pg_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_bodies_by_pg_ids([pg_id])

        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_uuids_are_skipped_not_raised(self, article_repo, mock_pool):
        """Invalid UUID strings must be skipped with a warning, not raised.

        Graph DBs may carry historical dirty ``pg_id`` values; one bad pg_id
        must NOT abort the entire batch (rule 12).
        """
        valid_pg_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([_make_body_row(valid_pg_id, "Valid body.")])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_bodies_by_pg_ids(["not-a-uuid", valid_pg_id, "also-bad"])

        assert valid_pg_id in result
        assert len(result) == 1
        mock_pool.session.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_invalid_uuids_returns_empty_dict_without_db_hit(
        self, article_repo, mock_pool
    ):
        """When every pg_id is invalid, return empty dict without DB hit."""
        result = await article_repo.fetch_bodies_by_pg_ids(["not-a-uuid", "also-bad"])

        assert result == {}
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_batch_triggers_chunked_queries(self, article_repo, mock_pool):
        """Batches > CHUNK_SIZE (500) must be split into multiple queries."""
        # 600 valid UUIDs -> 2 chunks (500 + 100)
        pg_ids = [str(uuid.uuid4()) for _ in range(600)]
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([_make_body_row(pg_ids[0], "First")])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await article_repo.fetch_bodies_by_pg_ids(pg_ids)

        # 2 chunks => 2 session.execute calls; session shared once.
        assert mock_session.execute.await_count == 2
        mock_pool.session.assert_called_once()

        # Verify chunk-2 contains pg_ids[500:600] (not all 600).
        second_stmt = mock_session.execute.await_args_list[1][0][0]
        compiled = str(second_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert pg_ids[500].replace("-", "") in compiled
        assert pg_ids[499].replace("-", "") not in compiled

    @pytest.mark.asyncio
    async def test_query_uses_article_bodies_with_article_id_in_filter(
        self, article_repo, mock_pool
    ):
        """SELECT must target article_bodies and filter by article_id IN (:ids).

        Guards against regressions that query the ``articles`` VIEW (not
        updatable in DuckDB) or that filter by the wrong column.
        """
        pg_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([_make_body_row(pg_id, "Body text")])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await article_repo.fetch_bodies_by_pg_ids([pg_id])

        mock_session.execute.assert_awaited_once()
        executed_stmt = mock_session.execute.await_args[0][0]
        compiled = str(executed_stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "article_bodies" in compiled
        assert "IN" in compiled.upper()
