# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T021 RED: ArticleRepo.fetch_titles_by_pg_ids batch metadata lookup.

When the graph DB Article node is slimmed down to only ``id`` + ``pg_id``
(see design.md §D2), any caller that previously read ``title`` /
``category`` / ``publish_time`` / ``score`` from the graph node must now
batch-fetch those fields from the relational DB (PostgreSQL or DuckDB)
via ``pg_id``. This test asserts the contract of that batch lookup.

Contract:
    Input:  ``pg_ids: list[str]`` (UUID strings, may be empty)
    Output: ``dict[str, dict]`` mapping ``pg_id`` -> ``{title, category,
            publish_time, score}``. ``pg_id`` keys are strings.
            Missing pg_ids are omitted from the result (not None).
    Edge:
        - Empty input -> empty dict (no DB hit)
        - Partial match -> only matched entries returned
        - ``publish_time`` / ``score`` may be ``None`` (terminal articles)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.storage.postgres.article_repo import ArticleRepo


def _make_row(
    pg_id: str,
    title: str,
    category: str,
    publish_time: datetime | None,
    score: float | None,
) -> tuple:
    """Build a fake result row matching the SELECT column order."""
    return (uuid.UUID(pg_id), title, category, publish_time, score)


class TestFetchTitlesByPgIds:
    """Tests for ArticleRepo.fetch_titles_by_pg_ids (T021)."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def article_repo(self, mock_pool):
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty_dict_without_db_hit(self, article_repo, mock_pool):
        """Empty pg_ids list short-circuits without opening a session."""
        result = await article_repo.fetch_titles_by_pg_ids([])

        assert result == {}
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_matched_returns_full_mapping(self, article_repo, mock_pool):
        """When every pg_id matches, return a mapping with all four fields."""
        pg_id_1 = str(uuid.uuid4())
        pg_id_2 = str(uuid.uuid4())
        publish_time = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_row(pg_id_1, "Article One", "tech", publish_time, 0.85),
                _make_row(pg_id_2, "Article Two", "finance", None, 0.5),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_titles_by_pg_ids([pg_id_1, pg_id_2])

        assert set(result.keys()) == {pg_id_1, pg_id_2}

        entry_1 = result[pg_id_1]
        assert entry_1["title"] == "Article One"
        assert entry_1["category"] == "tech"
        assert entry_1["publish_time"] == publish_time
        assert entry_1["score"] == 0.85

        entry_2 = result[pg_id_2]
        assert entry_2["title"] == "Article Two"
        assert entry_2["category"] == "finance"
        assert entry_2["publish_time"] is None
        assert entry_2["score"] == 0.5

    @pytest.mark.asyncio
    async def test_partial_match_returns_only_found(self, article_repo, mock_pool):
        """When only some pg_ids exist, return only the matched subset."""
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
        assert result[pg_id_found]["title"] == "Found"

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

        result = await article_repo.fetch_titles_by_pg_ids([pg_id])

        assert result == {}

    @pytest.mark.asyncio
    async def test_terminal_article_with_null_fields_is_included(self, article_repo, mock_pool):
        """Terminal articles (NULL publish_time / score) must still be returned.

        Terminal articles are persisted with neutral fallbacks but may still
        carry NULL publish_time / score when imported from legacy data. The
        batch lookup must include them so callers can render titles uniformly.
        """
        pg_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_row(pg_id, "Terminal Article", "其他", None, None),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_titles_by_pg_ids([pg_id])

        assert pg_id in result
        assert result[pg_id]["title"] == "Terminal Article"
        assert result[pg_id]["category"] == "其他"
        assert result[pg_id]["publish_time"] is None
        assert result[pg_id]["score"] is None

    @pytest.mark.asyncio
    async def test_invalid_uuids_are_skipped_not_raised(self, article_repo, mock_pool):
        """Invalid UUID strings must be skipped with a warning, not raised.

        Graph DBs may carry historical dirty ``pg_id`` values (truncated
        strings, None coerced to "None", etc.). One bad pg_id must NOT
        abort the entire batch (rule 12: failures must be explicit but
        not silently abort partial success).
        """
        valid_pg_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_row(valid_pg_id, "Valid", "tech", None, None),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.fetch_titles_by_pg_ids(
            [
                "not-a-uuid",
                valid_pg_id,
                "also-not-uuid",
            ]
        )

        # Only the valid UUID was queried & returned
        assert valid_pg_id in result
        assert len(result) == 1
        # Session was opened exactly once (shared across all chunks)
        mock_pool.session.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_invalid_uuids_returns_empty_dict(self, article_repo, mock_pool):
        """When every pg_id is invalid, return empty dict without DB hit."""
        result = await article_repo.fetch_titles_by_pg_ids(
            [
                "not-a-uuid",
                "also-bad",
            ]
        )

        assert result == {}
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_batch_triggers_chunked_queries(self, article_repo, mock_pool):
        """Batches > CHUNK_SIZE (500) must be split into multiple queries.

        Aligns with bulk_upsert's chunk pattern; prevents PG parameter
        limit blowup and DuckDB plan-cache bloat on >1000 id lists.
        """
        # 600 valid UUIDs -> 2 chunks (500 + 100)
        pg_ids = [str(uuid.uuid4()) for _ in range(600)]
        # Each chunk returns a single-row stub; we only care about call count
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_row(pg_ids[0], "First", "tech", None, None),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await article_repo.fetch_titles_by_pg_ids(pg_ids)

        # 2 chunks => 2 session.execute calls; session itself is opened once
        # (shared across chunks for read-only queries).
        assert mock_session.execute.await_count == 2
        mock_pool.session.assert_called_once()

        # Verify chunk-2 actually contains pg_ids[500:600] (not all 600).
        # Compiles the 2nd execute() stmt with literal binds to inspect.
        # Note: SQLAlchemy literal_binds renders UUIDs as 32-char hex
        # (no dashes), so compare against the dashed UUID's hex form.
        second_stmt = mock_session.execute.await_args_list[1][0][0]
        compiled = str(second_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert pg_ids[500].replace("-", "") in compiled
        assert pg_ids[499].replace("-", "") not in compiled

    @pytest.mark.asyncio
    async def test_5k_pg_ids_triggers_10_chunks(self, article_repo, mock_pool):
        """5K pg_ids must split into 10 chunks of 500 each.

        Stress test for the chunking boundary at scale: verifies that
        even with 5000 entries the implementation does not collapse to
        a single mega-query (which would blow PG parameter limits).
        """
        pg_ids = [str(uuid.uuid4()) for _ in range(5000)]
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])  # no matches

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await article_repo.fetch_titles_by_pg_ids(pg_ids)

        # 5000 / 500 = 10 chunks; session shared once.
        assert mock_session.execute.await_count == 10
        mock_pool.session.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_uses_articles_core_with_id_in_filter(self, article_repo, mock_pool):
        """The SELECT must target articles_core and filter by id IN (:ids).

        Guards against regressions that query the ``articles`` VIEW
        (which is not updatable in DuckDB) or that filter by source_url
        instead of id. Note: this asserts on SQLAlchemy compile() output,
        which is an implementation detail — if SQLAlchemy changes the
        compiled representation, update this test rather than the
        production code (the contract is "query articles_core by id").
        """
        pg_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter(
            [
                _make_row(pg_id, "T", "c", None, None),
            ]
        )

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await article_repo.fetch_titles_by_pg_ids([pg_id])

        mock_session.execute.assert_awaited_once()
        # Inspect the executed statement: compile to SQL string for inspection.
        executed_stmt = mock_session.execute.await_args[0][0]
        compiled = str(executed_stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "articles_core" in compiled
        assert "IN" in compiled.upper()
