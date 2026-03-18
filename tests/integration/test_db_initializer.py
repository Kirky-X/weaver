# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for database initializer module."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from core.db.initializer import (
    check_database_exists,
    initialize_database,
    parse_dsn,
    verify_tables,
)


@pytest.mark.integration
class TestDatabaseInitializerIntegration:
    """Integration tests for database initializer with real PostgreSQL."""

    @pytest.fixture
    def test_dsn(self):
        """Get test DSN from environment."""
        return os.getenv(
            "POSTGRES_DSN",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/weaver",
        )

    @pytest.mark.asyncio
    async def test_parse_dsn_from_settings(self, test_dsn):
        """Test parsing DSN from actual settings."""
        result = parse_dsn(test_dsn)
        assert result.database == "weaver"
        assert result.user == "postgres"
        assert result.port == 5432

    @pytest.mark.asyncio
    async def test_check_database_exists_real(self, test_dsn):
        """Test checking if database exists with real connection."""
        parsed = parse_dsn(test_dsn)

        result = await check_database_exists(parsed)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_tables_real(self, test_dsn):
        """Test verifying tables with real connection."""
        result = await verify_tables(test_dsn)
        assert result is True

    @pytest.mark.asyncio
    async def test_initialize_database_idempotent(self, test_dsn):
        """Test that initialize_database is idempotent."""
        result = await initialize_database(test_dsn)

        assert result["tables_verified"] is True
        assert result["database_created"] is False

    @pytest.mark.asyncio
    async def test_initialize_database_with_missing_tables(self, test_dsn):
        """Test initialization when tables might be missing."""
        with (
            patch(
                "core.db.initializer.verify_tables",
                AsyncMock(side_effect=[False, True]),
            ),
            patch("core.db.initializer.run_migrations") as mock_migrate,
        ):
            result = await initialize_database(test_dsn)

        assert result["migrations_run"] is True
        mock_migrate.assert_called_once()


@pytest.mark.integration
class TestDatabaseInitializerWithMock:
    """Integration tests using mocks for edge cases."""

    @pytest.fixture
    def mock_dsn(self):
        """Mock DSN for testing."""
        return "postgresql+asyncpg://testuser:testpass@localhost:5432/testdb"

    @pytest.mark.asyncio
    async def test_full_initialization_flow_new_database(self, mock_dsn):
        """Test full initialization flow for a new database."""
        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.check_database_exists",
                AsyncMock(return_value=False),
            ),
            patch(
                "core.db.initializer.create_database",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.verify_tables",
                AsyncMock(side_effect=[False, True]),
            ),
            patch(
                "core.db.initializer.run_migrations",
            ) as mock_migrate,
        ):
            result = await initialize_database(mock_dsn)

        assert result["database_created"] is True
        assert result["migrations_run"] is True
        assert result["tables_verified"] is True
        mock_migrate.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialization_with_connection_failure(self, mock_dsn):
        """Test initialization when PostgreSQL is not available."""

        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(side_effect=RuntimeError("PostgreSQL not available after 5s")),
            ),
            pytest.raises(RuntimeError, match="not available"),
        ):
            await initialize_database(mock_dsn, timeout=5.0)

    @pytest.mark.asyncio
    async def test_initialization_with_permission_denied(self, mock_dsn):
        """Test initialization when user lacks CREATEDB privilege."""

        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.check_database_exists",
                AsyncMock(return_value=False),
            ),
            patch(
                "core.db.initializer.create_database",
                AsyncMock(
                    side_effect=RuntimeError("Permission denied to create database 'testdb'")
                ),
            ),
            pytest.raises(RuntimeError, match="Permission denied"),
        ):
            await initialize_database(mock_dsn)

    @pytest.mark.asyncio
    async def test_initialization_with_migration_failure(self, mock_dsn):
        """Test initialization when migration fails."""
        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.check_database_exists",
                AsyncMock(return_value=True),
            ),
            patch(
                "core.db.initializer.verify_tables",
                AsyncMock(return_value=False),
            ),
            patch(
                "core.db.initializer.run_migrations",
                side_effect=Exception("Migration failed: syntax error"),
            ),
            pytest.raises(Exception, match="Migration failed"),
        ):
            await initialize_database(mock_dsn)

    @pytest.mark.asyncio
    async def test_initialization_tables_still_missing_after_migration(self, mock_dsn):
        """Test initialization when tables are still missing after migration."""
        with (
            patch(
                "core.db.initializer.wait_for_postgres",
                AsyncMock(),
            ),
            patch(
                "core.db.initializer.check_database_exists",
                AsyncMock(return_value=True),
            ),
            patch(
                "core.db.initializer.verify_tables",
                AsyncMock(return_value=False),
            ),
            patch(
                "core.db.initializer.run_migrations",
            ),
            pytest.raises(RuntimeError, match="Tables still missing"),
        ):
            await initialize_database(mock_dsn)
