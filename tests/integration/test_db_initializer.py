# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for database initializer module."""

import os

import pytest

from core.db.initializer import (
    check_database_exists,
    initialize_database,
    parse_dsn,
    verify_tables,
)


async def _check_postgres_available() -> bool:
    """Check if PostgreSQL is available."""
    try:
        from core.db.postgres import PostgresPool

        dsn = (
            f"postgresql+asyncpg://"
            f"{os.getenv('POSTGRES_USER', 'postgres')}:"
            f"{os.getenv('POSTGRES_PASSWORD', 'invalid')}@"
            f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
            f"{os.getenv('POSTGRES_PORT', '5432')}/"
            f"{os.getenv('POSTGRES_DATABASE', 'weaver')}"
        )
        pool = PostgresPool(dsn)
        await pool.startup()
        await pool.shutdown()
        return True
    except Exception:
        return False


@pytest.mark.integration
class TestDatabaseInitializerIntegration:
    """Integration tests for database initializer with real PostgreSQL."""

    @pytest.fixture
    def test_dsn(self, monkeypatch):
        """Get test DSN. Override env to avoid E2E test pollution."""
        # Prevent E2E test env vars from leaking into this test
        monkeypatch.delenv("WEAVER_POSTGRES__DSN", raising=False)
        monkeypatch.delenv("POSTGRES_DSN", raising=False)
        # Use port 5432 (Docker weaver stack) - read from env for CI compatibility
        return (
            f"postgresql+asyncpg://"
            f"{os.getenv('POSTGRES_USER', 'postgres')}:"
            f"{os.getenv('POSTGRES_PASSWORD', 'invalid')}@"
            f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
            f"{os.getenv('POSTGRES_PORT', '5432')}/"
            f"{os.getenv('POSTGRES_DATABASE', 'weaver')}"
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
        if not await _check_postgres_available():
            pytest.skip("PostgreSQL not available")

        parsed = parse_dsn(test_dsn)

        result = await check_database_exists(parsed)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_tables_real(self, test_dsn):
        """Test verifying tables with real connection."""
        if not await _check_postgres_available():
            pytest.skip("PostgreSQL not available")

        result = await verify_tables(test_dsn)
        assert result is True

    @pytest.mark.asyncio
    async def test_initialize_database_idempotent(self, test_dsn):
        """Test that initialize_database is idempotent."""
        if not await _check_postgres_available():
            pytest.skip("PostgreSQL not available")

        result = await initialize_database(test_dsn)

        assert result["tables_verified"] is True
        assert result["database_created"] is False
