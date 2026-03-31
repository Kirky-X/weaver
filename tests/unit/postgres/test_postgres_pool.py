# Copyright (c) 2026 KirkyX. All Rights Reserved
"""PostgreSQL database unit tests.

Tests for PostgreSQL connection pool management with proper mocking.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestPostgresPool:
    """Tests for PostgreSQL connection pool."""

    @pytest.mark.asyncio
    async def test_pool_creation(self) -> None:
        """Test PostgreSQL pool creation and initialization."""
        from core.db.postgres import PostgresPool

        pool = PostgresPool(
            dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb",
            pool_size=10,
            max_overflow=20,
        )

        assert pool._dsn == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        assert pool._pool_size == 10
        assert pool._max_overflow == 20
        assert pool._engine is None  # Engine created on startup

    @pytest.mark.asyncio
    async def test_pool_startup_success(self) -> None:
        """Test successful pool startup."""
        from core.db.postgres import PostgresPool

        # Create mock engine
        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        # Mock the connect context manager
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=mock_connect_cm)

        with patch("core.db.postgres.create_async_engine", return_value=mock_engine):
            pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb")

            await pool.startup()

            assert pool._engine == mock_engine
            assert pool._session_factory is not None

    @pytest.mark.asyncio
    async def test_pool_startup_failure(self) -> None:
        """Test pool startup failure."""
        from core.db.postgres import PostgresPool

        with patch("core.db.postgres.create_async_engine") as mock_create:
            mock_create.side_effect = ConnectionError("Connection refused")

            pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb")

            with pytest.raises(ConnectionError, match="Connection refused"):
                await pool.startup()

    @pytest.mark.asyncio
    async def test_pool_shutdown(self) -> None:
        """Test closing the connection pool."""
        from core.db.postgres import PostgresPool

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=mock_connect_cm)

        with patch("core.db.postgres.create_async_engine", return_value=mock_engine):
            pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb")

            await pool.startup()
            await pool.shutdown()

            mock_engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_pool_engine_property(self) -> None:
        """Test accessing the engine property."""
        from core.db.postgres import PostgresPool

        mock_engine = AsyncMock()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=mock_connect_cm)

        with patch("core.db.postgres.create_async_engine", return_value=mock_engine):
            pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb")

            await pool.startup()
            result = pool.engine
            assert result == mock_engine

    @pytest.mark.asyncio
    async def test_pool_engine_not_initialized(self) -> None:
        """Test accessing engine before initialization."""
        from core.db.postgres import PostgresPool

        pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb")

        # Engine should be None before startup
        assert pool._engine is None

        # Accessing engine property should raise RuntimeError when not initialized
        with pytest.raises(RuntimeError, match="PostgresPool not started"):
            _ = pool.engine


class TestPostgresTransactions:
    """Tests for PostgreSQL transaction handling."""

    @pytest.mark.asyncio
    async def test_session_creation(self) -> None:
        """Test session creation from pool."""
        from core.db.postgres import PostgresPool

        mock_engine = AsyncMock()

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=mock_connect_cm)

        with patch("core.db.postgres.create_async_engine", return_value=mock_engine):
            pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb")

            await pool.startup()

            # Verify session factory was created
            assert pool._session_factory is not None

            # Create a session (should work without errors)
            session = pool.session()
            assert session is not None


class TestPostgresErrorHandling:
    """Tests for PostgreSQL error handling."""

    @pytest.mark.asyncio
    async def test_connection_timeout(self) -> None:
        """Test handling connection timeout during startup."""
        from core.db.postgres import PostgresPool

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        # Mock connection to fail with timeout
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = ConnectionError("Connection timeout")

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=mock_connect_cm)

        with patch("core.db.postgres.create_async_engine", return_value=mock_engine):
            pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/testdb")

            with pytest.raises(ConnectionError, match="timeout"):
                await pool.startup()

    @pytest.mark.asyncio
    async def test_invalid_credentials(self) -> None:
        """Test handling invalid credentials."""
        from core.db.postgres import PostgresPool

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        # Mock authentication failure
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = ConnectionError("password authentication failed")

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=mock_connect_cm)

        with patch("core.db.postgres.create_async_engine", return_value=mock_engine):
            pool = PostgresPool(dsn="postgresql+asyncpg://user:wrongpass@localhost:5432/testdb")

            with pytest.raises(ConnectionError, match="password authentication failed"):
                await pool.startup()

    @pytest.mark.asyncio
    async def test_database_not_exists(self) -> None:
        """Test handling non-existent database."""
        from core.db.postgres import PostgresPool

        mock_engine = AsyncMock()
        mock_engine.dispose = AsyncMock()

        # Mock database not exists error
        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = ConnectionError('database "nonexistent" does not exist')

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = MagicMock(return_value=mock_connect_cm)

        with patch("core.db.postgres.create_async_engine", return_value=mock_engine):
            pool = PostgresPool(dsn="postgresql+asyncpg://user:pass@localhost:5432/nonexistent")

            with pytest.raises(ConnectionError, match='database "nonexistent" does not exist'):
                await pool.startup()
