# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for core.db.initializer module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db.initializer import (
    INIT_RETRY_DELAY,
    PER_CONNECTION_TIMEOUT,
    REQUIRED_NEO4J_CONSTRAINTS,
    REQUIRED_TABLES,
    DatabaseInitError,
    ParsedDSN,
)


class TestDatabaseInitError:
    """Test DatabaseInitError exception."""

    def test_init_with_message_only(self):
        """Test initialization with message only."""
        error = DatabaseInitError("Init failed")

        assert error.message == "Init failed"
        assert error.details == []
        assert error.suggestions == []
        assert str(error) == "Init failed"

    def test_init_with_details(self):
        """Test initialization with details."""
        error = DatabaseInitError(
            "Init failed",
            details=["Table missing", "Connection timeout"],
        )

        assert error.message == "Init failed"
        assert error.details == ["Table missing", "Connection timeout"]
        assert "Table missing" in str(error)

    def test_init_with_suggestions(self):
        """Test initialization with suggestions."""
        error = DatabaseInitError(
            "Init failed",
            suggestions=["Run migrations", "Check connection"],
        )

        assert error.suggestions == ["Run migrations", "Check connection"]
        assert "Run migrations" in str(error)

    def test_init_with_both(self):
        """Test initialization with details and suggestions."""
        error = DatabaseInitError(
            "Init failed",
            details=["Error detail"],
            suggestions=["Fix suggestion"],
        )

        assert "Error detail" in str(error)
        assert "Fix suggestion" in str(error)

    def test_is_exception_subclass(self):
        """Test DatabaseInitError is Exception subclass."""
        error = DatabaseInitError("Test")
        assert isinstance(error, Exception)


class TestParsedDSN:
    """Test ParsedDSN dataclass."""

    def test_create_parsed_dsn(self):
        """Test creating ParsedDSN."""
        dsn = ParsedDSN(
            driver="postgresql",
            user="admin",
            password="secret",
            host="localhost",
            port=5432,
            database="weaver",
        )

        assert dsn.driver == "postgresql"
        assert dsn.user == "admin"
        assert dsn.password == "secret"
        assert dsn.host == "localhost"
        assert dsn.port == 5432
        assert dsn.database == "weaver"


class TestConstants:
    """Test module constants."""

    def test_required_tables(self):
        """Test REQUIRED_TABLES contains expected tables."""
        assert "articles" in REQUIRED_TABLES
        assert "article_vectors" in REQUIRED_TABLES
        assert "entity_vectors" in REQUIRED_TABLES
        assert "source_authorities" in REQUIRED_TABLES
        assert len(REQUIRED_TABLES) == 4

    def test_neo4j_constraints(self):
        """Test REQUIRED_NEO4J_CONSTRAINTS structure."""
        assert len(REQUIRED_NEO4J_CONSTRAINTS) == 2

        constraint = REQUIRED_NEO4J_CONSTRAINTS[0]
        assert "name" in constraint
        assert "query" in constraint
        assert "description" in constraint
        assert "entity_name_type_unique" in constraint["query"]

    def test_timeout_constants(self):
        """Test timeout constants are reasonable."""
        assert PER_CONNECTION_TIMEOUT > 0
        assert INIT_RETRY_DELAY > 0
        assert PER_CONNECTION_TIMEOUT == 5.0
        assert INIT_RETRY_DELAY == 2.0


class TestParseDSN:
    """Test DSN parsing functionality."""

    def test_parse_postgresql_dsn(self):
        """Test parsing PostgreSQL DSN."""
        from core.db.initializer import _parse_dsn

        dsn = "postgresql://user:pass@localhost:5432/dbname"
        parsed = _parse_dsn(dsn)

        assert parsed.driver == "postgresql"
        assert parsed.user == "user"
        assert parsed.password == "pass"
        assert parsed.host == "localhost"
        assert parsed.port == 5432
        assert parsed.database == "dbname"

    def test_parse_dsn_without_port(self):
        """Test parsing DSN without port."""
        from core.db.initializer import _parse_dsn

        dsn = "postgresql://user:pass@localhost/dbname"
        parsed = _parse_dsn(dsn)

        assert parsed.host == "localhost"
        assert parsed.database == "dbname"

    def test_parse_invalid_dsn(self):
        """Test parsing invalid DSN raises error."""
        from core.db.initializer import _parse_dsn

        with pytest.raises(ValueError):
            _parse_dsn("invalid_dsn")


class TestCheckDatabaseExists:
    """Test database existence check."""

    @pytest.mark.asyncio
    async def test_database_exists(self):
        """Test check when database exists."""
        from core.db.initializer import _check_database_exists

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)

        result = await _check_database_exists(mock_conn, "weaver")

        assert result is True
        mock_conn.fetchval.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_does_not_exist(self):
        """Test check when database doesn't exist."""
        from core.db.initializer import _check_database_exists

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=False)

        result = await _check_database_exists(mock_conn, "weaver")

        assert result is False


class TestCreateDatabase:
    """Test database creation."""

    @pytest.mark.asyncio
    async def test_create_database(self):
        """Test creating database."""
        from core.db.initializer import _create_database

        mock_conn = AsyncMock()

        await _create_database(mock_conn, "weaver")

        mock_conn.execute.assert_called_once()
        assert "CREATE DATABASE" in str(mock_conn.execute.call_args)


class TestCheckRequiredTables:
    """Test required tables verification."""

    @pytest.mark.asyncio
    async def test_all_tables_exist(self):
        """Test when all required tables exist."""
        from core.db.initializer import _check_required_tables

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)

        missing = await _check_required_tables(mock_conn, REQUIRED_TABLES)

        assert missing == []

    @pytest.mark.asyncio
    async def test_missing_tables(self):
        """Test when some tables are missing."""
        from core.db.initializer import _check_required_tables

        mock_conn = AsyncMock()
        call_count = 0

        async def mock_fetchval(query):
            nonlocal call_count
            call_count += 1
            # First table exists, second doesn't
            return call_count == 1

        mock_conn.fetchval = mock_fetchval

        missing = await _check_required_tables(mock_conn, ["table1", "table2"])

        assert "table2" in missing


class TestRunAlembicMigration:
    """Test Alembic migration execution."""

    def test_run_upgrade(self):
        """Test running alembic upgrade."""
        from core.db.initializer import _run_alembic_migration

        with patch("core.db.initializer.command.upgrade") as mock_upgrade:
            with patch("core.db.initializer.Config") as mock_config:
                _run_alembic_migration("postgresql://localhost/db", "head")

                mock_upgrade.assert_called_once()

    def test_run_migration_handles_error(self):
        """Test migration handles errors."""
        from core.db.initializer import _run_alembic_migration

        with patch(
            "core.db.initializer.command.upgrade", side_effect=Exception("Migration failed")
        ):
            with patch("core.db.initializer.Config"):
                with pytest.raises(Exception, match="Migration failed"):
                    _run_alembic_migration("postgresql://localhost/db", "head")


class TestInitializeNeo4jConstraints:
    """Test Neo4j constraint initialization."""

    @pytest.mark.asyncio
    async def test_create_constraints(self):
        """Test creating Neo4j constraints."""
        from core.db.initializer import _initialize_neo4j_constraints

        mock_pool = AsyncMock()
        mock_pool.execute_query = AsyncMock()

        await _initialize_neo4j_constraints(mock_pool)

        # Should execute constraint queries
        assert mock_pool.execute_query.call_count >= len(REQUIRED_NEO4J_CONSTRAINTS)

    @pytest.mark.asyncio
    async def test_constraint_creation_failure(self):
        """Test constraint creation failure handling."""
        from core.db.initializer import _initialize_neo4j_constraints

        mock_pool = AsyncMock()
        mock_pool.execute_query = AsyncMock(side_effect=Exception("Constraint failed"))

        # Should not raise, just log error
        await _initialize_neo4j_constraints(mock_pool)


class TestDatabaseInitializerIntegration:
    """Integration tests for database initialization."""

    @pytest.mark.asyncio
    async def test_full_initialization_flow(self):
        """Test full database initialization flow."""
        from core.db.initializer import initialize_database

        dsn = "postgresql://user:pass@localhost:5432/weaver"

        with patch("core.db.initializer.asyncpg.connect") as mock_connect:
            with patch("core.db.initializer._check_database_exists", return_value=False):
                with patch("core.db.initializer._create_database"):
                    with patch("core.db.initializer._run_alembic_migration"):
                        await initialize_database(dsn)

                        # Should complete without error
                        assert True

    def test_initialization_error_provides_context(self):
        """Test initialization error provides helpful context."""
        error = DatabaseInitError(
            "Connection failed",
            details=["Host unreachable"],
            suggestions=["Check network", "Verify hostname"],
        )

        error_str = str(error)
        assert "Connection failed" in error_str
        assert "Host unreachable" in error_str
        assert "Check network" in error_str
        assert "Verify hostname" in error_str
