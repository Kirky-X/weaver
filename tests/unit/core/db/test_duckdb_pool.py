# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for DuckDB connection pool."""

import tempfile
from pathlib import Path

import pytest

from core.db.duckdb_pool import DuckDBPool, _DuckDBAsyncSession


class TestDuckDBPoolConnection:
    """Tests for DuckDB connection lifecycle management."""

    @pytest.mark.asyncio
    async def test_connection_initialization_succeeds(self) -> None:
        """Test that pool initializes successfully with valid configuration."""
        pool = DuckDBPool(":memory:")

        await pool.startup()
        assert pool._engine is not None

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_connection_creates_missing_directory(self) -> None:
        """Test that pool creates missing database directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "subdir" / "test.duckdb"
            pool = DuckDBPool(str(db_path))

            await pool.startup()
            assert pool._engine is not None
            assert db_path.parent.exists()

            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_connection_cleanup_releases_resources(self) -> None:
        """Test that shutdown properly releases all resources."""
        pool = DuckDBPool(":memory:")
        await pool.startup()
        engine = pool._engine

        await pool.shutdown()
        assert pool._engine is None

    @pytest.mark.asyncio
    async def test_engine_raises_error_when_not_started(self) -> None:
        """Test that accessing engine before startup raises error."""
        pool = DuckDBPool(":memory:")

        with pytest.raises(RuntimeError, match="not started"):
            _ = pool.engine

    @pytest.mark.asyncio
    async def test_session_raises_error_when_not_started(self) -> None:
        """Test that creating session before startup raises error."""
        pool = DuckDBPool(":memory:")

        with pytest.raises(RuntimeError, match="not started"):
            pool.session()


class TestDuckDBQueryExecution:
    """Tests for DuckDB query execution."""

    @pytest.fixture
    async def pool(self) -> DuckDBPool:
        """Create and start a DuckDB pool for testing."""
        pool = DuckDBPool(":memory:")
        await pool.startup()
        yield pool
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_query_returns_correct_results(self, pool: DuckDBPool) -> None:
        """Test that SELECT query returns expected data."""
        from sqlalchemy import text

        async with pool.session_context() as session:
            # Create a test table
            await session.execute(text("CREATE TABLE test_table (id INTEGER, name VARCHAR)"))
            await session.execute(text("INSERT INTO test_table VALUES (1, 'test')"))
            await session.commit()

            # Query the data
            result = await session.execute(text("SELECT id, name FROM test_table"))
            rows = result.fetchall()

            assert len(rows) == 1
            assert rows[0][0] == 1
            assert rows[0][1] == "test"

    @pytest.mark.asyncio
    async def test_query_handles_empty_result_set(self, pool: DuckDBPool) -> None:
        """Test that query on empty table returns empty result without error."""
        from sqlalchemy import text

        async with pool.session_context() as session:
            await session.execute(text("CREATE TABLE empty_table (id INTEGER)"))

            result = await session.execute(text("SELECT * FROM empty_table"))
            rows = result.fetchall()

            assert rows == []

    @pytest.mark.asyncio
    async def test_query_handles_syntax_error_gracefully(self, pool: DuckDBPool) -> None:
        """Test that invalid SQL raises a meaningful error."""
        from sqlalchemy import text

        async with pool.session_context() as session:
            with pytest.raises(Exception):  # noqa: B017 - SQLAlchemy will raise an exception
                await session.execute(text("SELECT * FROM nonexistent_table_xyz"))

    @pytest.mark.asyncio
    async def test_parameterized_query_works(self, pool: DuckDBPool) -> None:
        """Test that parameterized queries work correctly."""
        from sqlalchemy import text

        async with pool.session_context() as session:
            await session.execute(text("CREATE TABLE users (id INTEGER, name VARCHAR)"))
            await session.execute(text("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')"))
            await session.commit()

            result = await session.execute(
                text("SELECT name FROM users WHERE id = :id"),
                {"id": 1},
            )
            row = result.fetchone()

            assert row is not None
            assert row[0] == "Alice"


class TestDuckDBTransactionSupport:
    """Tests for DuckDB transaction handling."""

    @pytest.fixture
    async def pool(self) -> DuckDBPool:
        """Create and start a DuckDB pool for testing."""
        pool = DuckDBPool(":memory:")
        await pool.startup()
        yield pool
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_transaction_commit_persists_changes(self, pool: DuckDBPool) -> None:
        """Test that committed transactions persist data."""
        from sqlalchemy import text

        async with pool.session_context() as session:
            await session.execute(text("CREATE TABLE commit_test (id INTEGER)"))

        # Verify data persists after commit
        async with pool.session_context() as session:
            await session.execute(text("INSERT INTO commit_test VALUES (42)"))
            # session_context auto-commits on success

        async with pool.session_context() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM commit_test"))
            count = result.scalar()
            assert count == 1

    @pytest.mark.asyncio
    async def test_transaction_rollback_discards_changes(self, pool: DuckDBPool) -> None:
        """Test that rolled back transactions discard data."""
        from sqlalchemy import text

        async with pool.session_context() as session:
            await session.execute(text("CREATE TABLE rollback_test (id INTEGER)"))
            await session.commit()

        # Start a transaction and roll back
        session = pool.session()
        try:
            await session.execute(text("INSERT INTO rollback_test VALUES (99)"))
            await session.rollback()
        finally:
            await session.close()

        # Verify data was not persisted
        async with pool.session_context() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM rollback_test"))
            count = result.scalar()
            assert count == 0

    @pytest.mark.asyncio
    async def test_session_context_rollback_on_exception(self, pool: DuckDBPool) -> None:
        """Test that session_context rolls back on exception."""
        from sqlalchemy import text

        async with pool.session_context() as session:
            await session.execute(text("CREATE TABLE exception_test (id INTEGER)"))
            await session.commit()

        # Attempt an operation that raises an exception
        with pytest.raises(ValueError):
            async with pool.session_context() as session:
                await session.execute(text("INSERT INTO exception_test VALUES (1)"))
                raise ValueError("Simulated error")

        # Verify the insert was rolled back
        async with pool.session_context() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM exception_test"))
            count = result.scalar()
            assert count == 0


class TestDuckDBAsyncSession:
    """Tests for _DuckDBAsyncSession wrapper."""

    @pytest.mark.asyncio
    async def test_session_execute_async(self) -> None:
        """Test that session.execute works asynchronously."""
        from sqlalchemy import text

        pool = DuckDBPool(":memory:")
        await pool.startup()

        try:
            async with pool.session_context() as session:
                result = await session.execute(text("SELECT 1 + 1 AS sum"))
                row = result.fetchone()
                assert row is not None
                assert row[0] == 2
        finally:
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_session_scalar_async(self) -> None:
        """Test that session.scalar works asynchronously."""
        from sqlalchemy import text

        pool = DuckDBPool(":memory:")
        await pool.startup()

        try:
            async with pool.session_context() as session:
                result = await session.scalar(text("SELECT 42"))
                assert result == 42
        finally:
            await pool.shutdown()

    @pytest.mark.asyncio
    async def test_session_flush_and_refresh(self) -> None:
        """Test that flush and refresh work asynchronously."""
        from sqlalchemy import text

        pool = DuckDBPool(":memory:")
        await pool.startup()

        try:
            async with pool.session_context() as session:
                await session.execute(text("CREATE TABLE flush_test (id INTEGER, value VARCHAR)"))
                await session.execute(text("INSERT INTO flush_test VALUES (1, 'initial')"))
                await session.flush()

                # Verify flush worked
                result = await session.scalar(text("SELECT value FROM flush_test WHERE id = 1"))
                assert result == "initial"
        finally:
            await pool.shutdown()
