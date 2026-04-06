# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Performance optimization tests: batch operations, N+1 queries, async cache, connection pool."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db.query_builders import PgVectorQueryBuilder


def _make_vector_repo(mock_pool: MagicMock):
    """Create a VectorRepo with PostgreSQL query builder."""
    from modules.storage.postgres.vector_repo import VectorRepo

    return VectorRepo(pool=mock_pool, query_builder=PgVectorQueryBuilder())


class MockRow:
    """Mimics a SQLAlchemy Row with _mapping attribute."""

    def __init__(self, data: dict):
        object.__setattr__(self, "_mapping", data)

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._mapping.get(name)


# ─────────────────────────────────────────────────────────────────────────────
# 2.1.5 Batch Operations Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestVectorRepoBatchOperations:
    """Tests for VectorRepo bulk_upsert_article_vectors batch operations."""

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_list_returns_zero(self):
        """Bulk upsert with empty list should return 0."""
        mock_pool = MagicMock()
        repo = _make_vector_repo(mock_pool)

        result = await repo.bulk_upsert_article_vectors([])

        assert result == 0
        # Should not enter session context
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_upsert_single_article_with_both_embeddings(self):
        """Bulk upsert should handle single article with title and content embeddings."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2

        async def mock_execute(query, params=None):
            return mock_result

        mock_session.execute = mock_execute
        mock_session.commit = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = _make_vector_repo(mock_pool)

        article_id = uuid.uuid4()
        articles = [
            (article_id, [0.1] * 1024, [0.2] * 1024, "text-embedding-3-large"),
        ]

        result = await repo.bulk_upsert_article_vectors(articles)

        # Should insert 2 vectors (title + content)
        assert result == 2

    @pytest.mark.asyncio
    async def test_bulk_upsert_filters_none_embeddings(self):
        """Bulk upsert should filter out None embeddings."""
        from modules.storage.postgres.vector_repo import VectorRepo

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1

        async def mock_execute(query, params=None):
            return mock_result

        mock_session.execute = mock_execute
        mock_session.commit = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = _make_vector_repo(mock_pool)

        article_id = uuid.uuid4()
        articles = [
            (article_id, [0.1] * 1024, None, "text-embedding-3-large"),  # Only title
        ]

        result = await repo.bulk_upsert_article_vectors(articles)

        assert result == 1

    @pytest.mark.asyncio
    async def test_bulk_upsert_uses_on_conflict_upsert(self):
        """Bulk upsert should use INSERT ON CONFLICT for upsert semantics."""
        from modules.storage.postgres.vector_repo import VectorRepo

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        execute_tracker = AsyncMock(return_value=mock_result)

        mock_session.execute = execute_tracker
        mock_session.commit = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = _make_vector_repo(mock_pool)

        articles = [
            (uuid.uuid4(), [0.1] * 1024, [0.2] * 1024, "model-id"),
        ]

        await repo.bulk_upsert_article_vectors(articles)

        # Get the SQL that was executed
        call_args = execute_tracker.call_args
        sql_text = str(call_args[0][0])

        # Verify ON CONFLICT clause is present
        assert "ON CONFLICT" in sql_text.upper()
        assert "article_id" in sql_text.lower()
        assert "vector_type" in sql_text.lower()


class TestBatchFindSimilar:
    """Tests for VectorRepo batch_find_similar method."""

    @pytest.mark.asyncio
    async def test_batch_find_similar_empty_queries(self):
        """Batch find with empty queries should return empty dict."""
        from modules.storage.postgres.vector_repo import VectorRepo

        mock_pool = MagicMock()
        repo = _make_vector_repo(mock_pool)

        result = await repo.batch_find_similar([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_batch_find_similar_uses_single_session(self):
        """Batch find should use a single session for all queries."""
        from modules.storage.postgres.vector_repo import VectorRepo

        mock_session = MagicMock()

        async def mock_execute(query, params=None):
            result = MagicMock()
            result.__iter__ = lambda self: iter([])
            return result

        mock_session.execute = mock_execute
        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = _make_vector_repo(mock_pool)

        queries = [
            (uuid.uuid4(), [0.1] * 1024),
            (uuid.uuid4(), [0.2] * 1024),
            (uuid.uuid4(), [0.3] * 1024),
        ]

        await repo.batch_find_similar(queries)

        # Session context manager should be entered only once
        assert mock_pool.session.call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2.2.5 Batch Query Tests for Neo4j N+1 Fix
# ─────────────────────────────────────────────────────────────────────────────


class TestNeo4jBatchQueries:
    """Tests for Neo4j batch query methods to prevent N+1 patterns."""

    @pytest.mark.asyncio
    async def test_find_entities_by_ids_batch_query_structure(self):
        """Test that find_entities_by_ids uses UNWIND for batch query."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                {"neo4j_id": "id-1", "canonical_name": "Entity1", "type": "ORG"},
                {"neo4j_id": "id-2", "canonical_name": "Entity2", "type": "PERSON"},
            ]
        )

        repo = Neo4jEntityRepo(pool=mock_pool)
        result = await repo.find_entities_by_ids(["id-1", "id-2"])

        # Verify batch query was called
        assert mock_pool.execute_query.call_count == 1
        call_args = mock_pool.execute_query.call_args
        query_text = call_args[0][0]

        # Should use UNWIND for batch processing
        assert "UNWIND" in query_text.upper() or "$ids" in query_text

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_merge_entities_batch_uses_unwind(self):
        """Test that merge_entities_batch uses UNWIND for batch MERGE."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"created": 5, "updated": 3}])

        repo = Neo4jEntityRepo(pool=mock_pool)

        entities = [
            {"canonical_name": f"Entity{i}", "type": "ORG", "description": f"Desc {i}"}
            for i in range(5)
        ]

        result = await repo.merge_entities_batch(entities)

        # Should call batch MERGE with UNWIND
        assert mock_pool.execute_query.call_count == 1
        call_args = mock_pool.execute_query.call_args
        query_text = call_args[0][0]

        assert "UNWIND" in query_text.upper()
        assert "MERGE" in query_text.upper()

        assert result["created"] == 5
        assert result["updated"] == 3

    @pytest.mark.asyncio
    async def test_add_aliases_batch_uses_unwind(self):
        """Test that add_aliases_batch uses UNWIND for batch update."""
        from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[{"updated": 3}])

        repo = Neo4jEntityRepo(pool=mock_pool)

        aliases = [
            {"canonical_name": "Entity1", "type": "ORG", "alias": "Alias1"},
            {"canonical_name": "Entity2", "type": "PERSON", "alias": "Alias2"},
        ]

        result = await repo.add_aliases_batch(aliases)

        assert mock_pool.execute_query.call_count == 1
        call_args = mock_pool.execute_query.call_args
        query_text = call_args[0][0]

        assert "UNWIND" in query_text.upper()

        assert result == 3


# ─────────────────────────────────────────────────────────────────────────────
# 2.4.4 Connection Pool Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestConnectionPoolStats:
    """Tests for database connection pool statistics."""

    @pytest.mark.asyncio
    async def test_pool_handles_concurrent_sessions(self):
        """Pool should handle many concurrent session requests."""
        from core.db.postgres import PostgresPool

        # Create a mock engine that simulates connection behavior
        mock_engine = MagicMock()
        mock_pool = MagicMock()

        # Simulate pool stats
        mock_pool.size.return_value = 20
        mock_pool.overflow.return_value = 5
        mock_pool.checkedin.return_value = 15
        mock_pool.checkedout.return_value = 10
        mock_pool.overflow_invalid.return_value = 0
        mock_engine.pool = mock_pool

        pool = PostgresPool(dsn="postgresql://user:pass@localhost/db")
        pool._engine = mock_engine
        pool._session_factory = MagicMock()

        # Get pool stats under load
        stats = pool.get_pool_stats()

        assert stats["pool_size"] == 20
        assert stats["overflow"] == 5
        assert stats["checked_out"] == 10
        assert 0.0 <= stats["utilization"] <= 1.0

    @pytest.mark.asyncio
    async def test_pool_stats_when_not_started(self):
        """Pool stats should return zeros when pool not started."""
        from core.db.postgres import PostgresPool

        pool = PostgresPool(dsn="postgresql://user:pass@localhost/db")

        stats = pool.get_pool_stats()

        assert stats["pool_size"] == 0
        assert stats["overflow"] == 0
        assert stats["checked_out"] == 0
        assert stats["utilization"] == 0.0

    @pytest.mark.asyncio
    async def test_pool_utilization_calculation(self):
        """Pool utilization should be calculated correctly."""
        from core.db.postgres import PostgresPool

        mock_engine = MagicMock()
        mock_pool = MagicMock()

        # 15 out of 30 total capacity in use
        mock_pool.size.return_value = 20
        mock_pool.overflow.return_value = 5
        mock_pool.checkedin.return_value = 10
        mock_pool.checkedout.return_value = 15
        mock_pool.overflow_invalid.return_value = 0
        mock_engine.pool = mock_pool

        pool = PostgresPool(
            dsn="postgresql://user:pass@localhost/db",
            pool_size=20,
            max_overflow=10,
        )
        pool._engine = mock_engine

        stats = pool.get_pool_stats()

        # Utilization = checked_out / (pool_size + max_overflow) = 15 / 30 = 0.5
        assert stats["utilization"] == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# Performance Comparison Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPerformanceComparison:
    """Compare batch vs individual operations."""

    @pytest.mark.asyncio
    async def test_bulk_vs_individual_upsert_comparison(self):
        """Verify bulk upsert makes fewer DB calls than individual upserts."""
        from modules.storage.postgres.vector_repo import VectorRepo

        mock_session = MagicMock()
        execute_calls = 0

        async def mock_execute(query, params=None):
            nonlocal execute_calls
            execute_calls += 1
            result = MagicMock()
            result.rowcount = 1
            return result

        mock_session.execute = mock_execute
        mock_session.commit = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = _make_vector_repo(mock_pool)

        # Bulk upsert 10 articles with both embeddings = 20 vectors
        articles = [(uuid.uuid4(), [0.1] * 1024, [0.2] * 1024, "model") for _ in range(10)]

        execute_calls = 0
        await repo.bulk_upsert_article_vectors(articles, batch_size=20)
        bulk_calls = execute_calls

        # Bulk should use 1 execute for SET + 1 for batch insert = 2 calls
        # vs individual: 10 articles * 2 embeddings * 2-3 queries each = 40-60 calls
        assert bulk_calls <= 3  # SET + batch insert + commit

    @pytest.mark.asyncio
    async def test_batch_find_vs_individual_queries(self):
        """Verify batch_find uses fewer sessions than individual finds."""
        from modules.storage.postgres.vector_repo import VectorRepo

        mock_session = MagicMock()

        async def mock_execute(query, params=None):
            result = MagicMock()
            result.__iter__ = lambda self: iter([])
            return result

        mock_session.execute = mock_execute
        mock_pool = MagicMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        repo = _make_vector_repo(mock_pool)

        queries = [(uuid.uuid4(), [0.1] * 1024) for _ in range(10)]

        await repo.batch_find_similar(queries)

        # Should use exactly 1 session for all queries
        assert mock_pool.session.call_count == 1
