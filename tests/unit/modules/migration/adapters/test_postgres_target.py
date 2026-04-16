# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.migration.adapters.postgres_target module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.migration.adapters.postgres_target import PostgresTarget
from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import ColumnDef, MigrationSchema


class TestPostgresTargetInit:
    """Test PostgresTarget initialization."""

    def test_init(self):
        """Test initialization."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool.engine = mock_engine

        target = PostgresTarget(mock_pool)

        assert target._pool is mock_pool


class TestPostgresTargetEnsureSchema:
    """Test ensure_schema method."""

    @pytest.fixture
    def target(self):
        """Create PostgresTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool.engine = mock_engine
        return PostgresTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_ensure_schema_creates_table(self, target):
        """Test ensure_schema creates new table."""
        schema = MigrationSchema(
            table="users",
            columns=[
                ColumnDef(name="id", data_type="integer", nullable=False),
                ColumnDef(name="name", data_type="varchar(100)", nullable=True),
            ],
            primary_key="id",
        )

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = False  # Table doesn't exist
        mock_conn.execute.return_value = mock_result
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        target._engine.begin = MagicMock(return_value=mock_conn)

        await target.ensure_schema(schema)

    @pytest.mark.asyncio
    async def test_ensure_schema_adds_columns(self, target):
        """Test ensure_schema adds missing columns."""
        schema = MigrationSchema(
            table="users",
            columns=[
                ColumnDef(name="id", data_type="integer", nullable=False),
            ],
            primary_key="id",
        )

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = True  # Table exists
        mock_conn.execute.return_value = mock_result
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        target._engine.begin = MagicMock(return_value=mock_conn)

        await target.ensure_schema(schema)


class TestPostgresTargetWriteBatch:
    """Test write_batch method."""

    @pytest.fixture
    def target(self):
        """Create PostgresTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool.engine = mock_engine
        return PostgresTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_write_batch_empty(self, target):
        """Test write_batch with empty list."""
        count = await target.write_batch("users", [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_write_batch_inserts_rows(self, target):
        """Test write_batch inserts rows."""
        rows = [{"id": 1, "name": "test"}]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        target._engine.begin = MagicMock(return_value=mock_conn)

        count = await target.write_batch("users", rows)

        assert count == 1


class TestPostgresTargetVerify:
    """Test verify method."""

    @pytest.fixture
    def target(self):
        """Create PostgresTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool.engine = mock_engine
        return PostgresTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_verify_success(self, target):
        """Test verify succeeds when count matches."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 100
        mock_conn.execute.return_value = mock_result
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        target._engine.connect = MagicMock(return_value=mock_conn)

        result = await target.verify("users", 100)

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_fails_on_mismatch(self, target):
        """Test verify fails when count doesn't match."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 50
        mock_conn.execute.return_value = mock_result
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        target._engine.connect = MagicMock(return_value=mock_conn)

        with pytest.raises(ValidationFailedError):
            await target.verify("users", 100)


class TestPostgresTargetTruncate:
    """Test truncate method."""

    @pytest.fixture
    def target(self):
        """Create PostgresTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool.engine = mock_engine
        return PostgresTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_truncate(self, target):
        """Test truncate executes."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        target._engine.begin = MagicMock(return_value=mock_conn)

        await target.truncate("users")
