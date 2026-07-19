# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for CommunityVectorRepo — covers find_similar_communities and
upsert_community_vector methods.

Covers R-community-vector-repo-001 (NameError bug fix) through
R-community-vector-repo-005 (upsert error path).

Tests use mock RelationalPool and mock VectorQueryBuilder to isolate from
real database dependencies. Mock session.execute returns canned rows so
the SQL execution path can be verified without a real database.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from core.db.query_builders import DatabaseType
from modules.storage.postgres.community_vector_repo import CommunityVectorRepo


def _make_mock_session():
    """Create a mock async session with execute/commit/rollback/close."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


def _make_mock_pool(session):
    """Create a mock RelationalPool whose session() returns the given session.

    The pool.session() must return an async context manager that yields the
    mock session. Use MagicMock with __aenter__/__aexit__ configured.
    """
    pool = MagicMock()

    # pool.session() returns an async context manager
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    pool.session = MagicMock(return_value=ctx)
    return pool


def _make_mock_query_builder(database_type: DatabaseType, formatted_emb="[0.1,0.2]"):
    """Create a mock VectorQueryBuilder with given database_type."""
    qb = MagicMock()
    qb.database_type = database_type
    qb.format_embedding_param = MagicMock(return_value=formatted_emb)
    return qb


def _make_mock_row(community_id="c-001", score=0.85, title="Community A", summary="Summary A"):
    """Create a mock row with community_id, score, title, summary attributes."""
    row = MagicMock()
    row.community_id = community_id
    row.score = score
    row.title = title
    row.summary = summary
    return row


class TestFindSimilarCommunities:
    """Tests for CommunityVectorRepo.find_similar_communities — R-community-vector-repo-002/003."""

    @pytest.mark.asyncio
    async def test_find_similar_communities_pg_mode_executes_hnsw_ef_search(self):
        """PG mode must execute SET hnsw.ef_search = 60 before the search query."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.POSTGRES)

        # Configure session.execute to return empty result
        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[])
        session.execute.return_value = result_mock

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        await repo.find_similar_communities(embedding=[0.1, 0.2], limit=5, threshold=0.8)

        # First call should be SET hnsw.ef_search; second is the search query
        assert session.execute.await_count >= 2, (
            f"PG mode expected >= 2 session.execute calls (SET + search), "
            f"got {session.execute.await_count}"
        )
        first_call = session.execute.await_args_list[0]
        first_stmt = first_call.args[0]
        # stmt should be a text() object; compare string
        stmt_str = str(first_stmt)
        assert (
            "SET hnsw.ef_search = 60" in stmt_str
        ), f"First session.execute in PG mode should be SET hnsw.ef_search, got: {stmt_str}"

    @pytest.mark.asyncio
    async def test_find_similar_communities_duckdb_mode_skips_hnsw(self):
        """DuckDB mode must NOT execute SET hnsw.ef_search (verifies T001 bug fix).

        Before T001 fix, DatabaseType was undefined → NameError on PG check.
        After fix, DuckDB branch correctly skips the SET statement.
        """
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.DUCKDB)

        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[])
        session.execute.return_value = result_mock

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        await repo.find_similar_communities(embedding=[0.1, 0.2])

        # Only ONE execute call (the search query), no SET hnsw.ef_search
        assert session.execute.await_count == 1, (
            f"DuckDB mode expected 1 session.execute call (search only), "
            f"got {session.execute.await_count}"
        )
        stmt_str = str(session.execute.await_args_list[0].args[0])
        assert (
            "SET hnsw.ef_search" not in stmt_str
        ), f"DuckDB mode must not execute SET hnsw.ef_search, but got: {stmt_str}"

    @pytest.mark.asyncio
    async def test_find_similar_communities_returns_mapped_views(self):
        """Returns list[CommunitySearchResultView] with correct fields from rows."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.DUCKDB)

        rows = [
            _make_mock_row("c-001", 0.95, "Community A", "Summary A"),
            _make_mock_row("c-002", 0.88, "Community B", "Summary B"),
        ]
        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=rows)
        session.execute.return_value = result_mock

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        results = await repo.find_similar_communities(embedding=[0.1, 0.2])

        assert len(results) == 2, f"Expected 2 results, got {len(results)}"
        assert results[0].community_id == "c-001"
        assert results[0].score == 0.95
        assert results[0].title == "Community A"
        assert results[0].summary == "Summary A"
        assert results[1].community_id == "c-002"
        assert results[1].score == 0.88

    @pytest.mark.asyncio
    async def test_find_similar_communities_passes_threshold_and_limit_params(self):
        """session.execute must receive threshold and limit as SQL parameters."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.DUCKDB)

        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[])
        session.execute.return_value = result_mock

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        await repo.find_similar_communities(embedding=[0.1, 0.2], limit=10, threshold=0.75)

        # Get the search query call (first call in DuckDB mode)
        call_args = session.execute.await_args_list[0]
        params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs
        assert isinstance(params, dict), f"Expected dict params, got {type(params)}"
        assert (
            params.get("threshold") == 0.75
        ), f"Expected threshold=0.75, got {params.get('threshold')}"
        assert params.get("limit") == 10, f"Expected limit=10, got {params.get('limit')}"
        assert "embedding" in params, "Missing 'embedding' in params"

    @pytest.mark.asyncio
    async def test_find_similar_communities_propagates_session_exception(self):
        """session.execute raising must propagate (not be swallowed)."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.DUCKDB)

        session.execute.side_effect = RuntimeError("DB connection lost")

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        with pytest.raises(RuntimeError, match="DB connection lost"):
            await repo.find_similar_communities(embedding=[0.1, 0.2])


class TestUpsertCommunityVector:
    """Tests for CommunityVectorRepo.upsert_community_vector — R-community-vector-repo-004/005."""

    @pytest.mark.asyncio
    async def test_upsert_inserts_with_all_8_fields(self):
        """session.execute must receive all 8 fields as SQL parameters."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.POSTGRES, formatted_emb="[0.5]")

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        await repo.upsert_community_vector(
            community_id="c-uuid-001",
            embedding=[0.5],
            title="Community Title",
            summary="Community Summary",
            entity_count=10,
            article_count=5,
            rank=8.5,
            model_id="text-embedding-3-large",
        )

        assert session.execute.await_count == 1, "upsert should call execute exactly once"
        call_args = session.execute.await_args
        params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs
        assert isinstance(params, dict)

        # Verify all 8 fields
        assert params.get("community_id") == "c-uuid-001"
        assert (
            params.get("embedding") == "[0.5]"
        ), f"Expected formatted embedding '[0.5]', got {params.get('embedding')}"
        assert params.get("model_id") == "text-embedding-3-large"
        assert params.get("title") == "Community Title"
        assert params.get("summary") == "Community Summary"
        assert params.get("entity_count") == 10
        assert params.get("article_count") == 5
        assert params.get("rank") == 8.5

        # Verify SQL contains ON CONFLICT (community_id) DO UPDATE
        stmt_str = str(call_args.args[0])
        assert (
            "ON CONFLICT" in stmt_str.upper()
        ), f"upsert SQL must contain ON CONFLICT, got: {stmt_str}"
        assert "community_id" in stmt_str

    @pytest.mark.asyncio
    async def test_upsert_calls_commit(self):
        """upsert must call session.commit() exactly once."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.POSTGRES)

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        await repo.upsert_community_vector(community_id="c-1", embedding=[0.1])

        assert (
            session.commit.await_count == 1
        ), f"Expected 1 commit call, got {session.commit.await_count}"

    @pytest.mark.asyncio
    async def test_upsert_formats_embedding_via_query_builder(self):
        """query_builder.format_embedding_param must be called with raw embedding."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.POSTGRES, formatted_emb="[0.7,0.8,0.9]")

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        await repo.upsert_community_vector(community_id="c-1", embedding=[0.7, 0.8, 0.9])

        qb.format_embedding_param.assert_called_once_with([0.7, 0.8, 0.9])

        # And the formatted result must be passed to session.execute
        params = session.execute.await_args.args[1]
        assert params.get("embedding") == "[0.7,0.8,0.9]"

    @pytest.mark.asyncio
    async def test_upsert_default_model_id_is_text_embedding_3_large(self):
        """When model_id not provided, default 'text-embedding-3-large' must be used."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.POSTGRES)

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        # Note: do NOT pass model_id
        await repo.upsert_community_vector(community_id="c-1", embedding=[0.1])

        params = session.execute.await_args.args[1]
        assert (
            params.get("model_id") == "text-embedding-3-large"
        ), f"Default model_id should be 'text-embedding-3-large', got {params.get('model_id')}"

    @pytest.mark.asyncio
    async def test_upsert_propagates_session_exception_without_commit(self):
        """When session.execute raises, exception must propagate and commit must NOT be called."""
        session = _make_mock_session()
        pool = _make_mock_pool(session)
        qb = _make_mock_query_builder(DatabaseType.POSTGRES)

        session.execute.side_effect = RuntimeError("Disk full")

        repo = CommunityVectorRepo(pool=pool, query_builder=qb)
        with pytest.raises(RuntimeError, match="Disk full"):
            await repo.upsert_community_vector(community_id="c-1", embedding=[0.1])

        # commit must NOT be called when execute failed
        assert session.commit.await_count == 0, (
            f"commit should not be called after execute failure, "
            f"but got {session.commit.await_count} calls"
        )
