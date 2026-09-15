# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Regression tests for container/core HIGH findings (OCR report).

Covers: /#87 (duckdb session lock), (traverse relation_types),
(postgres rollback masking), /#27 (query builder interpolation).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from core.db.graph_query_builders import Neo4jQueryBuilder
from core.db.query_builders import (
    DuckDBVectorQueryBuilder,
    EntitySimilarityQuery,
    PgVectorQueryBuilder,
    SimilarityQuery,
    validate_param_placeholder,
    validate_threshold,
)
from core.db.safe_query import InvalidIdentifierError


class TestTraverseQueryRelationTypes:
    """relation_types must reach the generated query."""

    def test_neo4j_query_uses_relation_types(self) -> None:
        query = Neo4jQueryBuilder().build_traverse_query(
            max_depth=3, relation_types=["RELATED_TO", "CAUSES"]
        )
        assert "[r:RELATED_TO|CAUSES*1..3]" in query
        # Explicit list replaces the hardcoded exclusions
        assert "MENTIONS" not in query

    def test_neo4j_default_exclusions_preserved(self) -> None:
        query = Neo4jQueryBuilder().build_traverse_query(max_depth=2)
        assert "[r*1..2]" in query
        assert "type(r[-1]) <> 'MENTIONS'" in query

    def test_neo4j_invalid_relation_type_rejected(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            Neo4jQueryBuilder().build_traverse_query(
                max_depth=2, relation_types=["BAD TYPE; DROP TABLE"]
            )

    def test_neo4j_confidence_filter_combined_with_types(self) -> None:
        query = Neo4jQueryBuilder().build_traverse_query(
            max_depth=2, relation_types=["RELATED_TO"], min_confidence=0.5
        )
        assert "coalesce(r.weight, 1.0) >= 0.5" in query


class TestQueryBuilderInterpolation:
    """/#27: numeric coercion and placeholder validation."""

    def test_validate_threshold_rejects_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="must be a number"):
            validate_threshold("0.9) OR (1=1")

    def test_pg_entity_query_coerces_threshold(self) -> None:
        builder = PgVectorQueryBuilder()
        config = EntitySimilarityQuery(threshold=0.9, limit=5)
        query = builder.build_find_similar_entities_query(config)
        assert ">= 0.9" in query

    def test_pg_entity_query_rejects_injection_threshold(self) -> None:
        builder = PgVectorQueryBuilder()
        config = EntitySimilarityQuery(threshold="0.5; DROP TABLE entity_vectors", limit=5) # type: ignore[arg-type]
        with pytest.raises(ValueError):
            builder.build_find_similar_entities_query(config)

    def test_duckdb_entity_query_rejects_injection_threshold(self) -> None:
        builder = DuckDBVectorQueryBuilder()
        config = EntitySimilarityQuery(threshold="0.5; DROP TABLE entity_vectors", limit=5) # type: ignore[arg-type]
        with pytest.raises(ValueError):
            builder.build_find_similar_entities_query(config)

    def test_validate_param_placeholder_accepts_valid(self) -> None:
        assert validate_param_placeholder(":category") == ":category"
        assert validate_param_placeholder(":model_id") == ":model_id"

    def test_validate_param_placeholder_rejects_injection(self) -> None:
        for bad in (":cat; DROP TABLE x", "category", ":1bad", "", None):
            with pytest.raises(ValueError, match="placeholder"):
                validate_param_placeholder(bad) # type: ignore[arg-type]

    def test_pg_similar_articles_rejects_bad_placeholder(self) -> None:
        builder = PgVectorQueryBuilder()
        config = SimilarityQuery(
            category_param=":c; DROP TABLE articles",
            filter_by_category=True,
        )
        with pytest.raises(ValueError, match="placeholder"):
            builder.build_find_similar_articles_query(config)


class TestDuckDBSessionLock:
    """/#87: rollback/close share the :memory: connection lock."""

    @pytest.fixture
    async def pool(self): # type: ignore[no-untyped-def]
        from core.db.duckdb_pool import DuckDBPool

        pool = DuckDBPool(":memory:")
        await pool.startup()
        yield pool
        await pool.shutdown()

    async def test_rollback_waits_for_lock(self, pool) -> None: # type: ignore[no-untyped-def]
        import asyncio

        session = pool.session()
        assert session._lock is not None

        # Hold the shared lock; rollback must wait instead of running immediately
        async with session._lock:
            task = asyncio.create_task(session.rollback())
            await asyncio.sleep(0)
            assert not task.done()
        await asyncio.wait_for(task, timeout=2)

    async def test_close_waits_for_lock(self, pool) -> None: # type: ignore[no-untyped-def]
        import asyncio

        session = pool.session()
        async with session._lock:
            task = asyncio.create_task(session.close())
            await asyncio.sleep(0)
            assert not task.done()
        await asyncio.wait_for(task, timeout=2)


class TestPostgresRollbackMasking:
    """a failing rollback must not mask the original error."""

    async def test_original_exception_propagates_when_rollback_fails(self) -> None:
        from core.db.postgres import PostgresPool

        pool = PostgresPool.__new__(PostgresPool)
        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock(side_effect=RuntimeError("connection broken"))
        session.close = AsyncMock()

        factory = MagicMock(return_value=session)
        pool._session_factory = factory # type: ignore[attr-defined]
        pool._engine = MagicMock() # type: ignore[attr-defined]

        with pytest.raises(ValueError, match="original failure"):
            async with pool.session_context() as _session:
                raise ValueError("original failure")

        session.rollback.assert_awaited_once()
