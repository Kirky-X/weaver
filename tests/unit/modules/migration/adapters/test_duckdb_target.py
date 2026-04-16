# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.migration.adapters.duckdb_target module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.migration.adapters.duckdb_target import DuckDBTarget
from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import ColumnDef, MigrationSchema


class TestDuckDBTargetInit:
    """Test DuckDBTarget initialization."""

    def test_init(self):
        """Test initialization."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool._engine = mock_engine

        target = DuckDBTarget(mock_pool)

        assert target._pool is mock_pool


class TestDuckDBTargetEnsureSchema:
    """Test ensure_schema method."""

    @pytest.fixture
    def target(self):
        """Create DuckDBTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool._engine = mock_engine
        return DuckDBTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_ensure_schema_creates_table(self, target):
        """Test ensure_schema creates new table."""
        schema = MigrationSchema(
            table="users",
            columns=[
                ColumnDef(name="id", data_type="INTEGER", nullable=False),
                ColumnDef(name="name", data_type="VARCHAR", nullable=True),
            ],
            primary_key="id",
        )

        with patch.object(target, "_run_sync") as mock_run:
            mock_run.return_value = None
            await target.ensure_schema(schema)


class TestDuckDBTargetWriteBatch:
    """Test write_batch method."""

    @pytest.fixture
    def target(self):
        """Create DuckDBTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool._engine = mock_engine
        return DuckDBTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_write_batch_empty(self, target):
        """Test write_batch with empty list."""
        count = await target.write_batch("users", [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_write_batch_inserts_rows(self, target):
        """Test write_batch inserts rows."""
        rows = [{"id": 1, "name": "test"}]

        with patch.object(target, "_run_sync") as mock_run:
            mock_run.return_value = 1
            count = await target.write_batch("users", rows)

            assert count == 1


class TestDuckDBTargetVerify:
    """Test verify method."""

    @pytest.fixture
    def target(self):
        """Create DuckDBTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool._engine = mock_engine
        return DuckDBTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_verify_success(self, target):
        """Test verify succeeds when count matches."""
        with patch.object(target, "_run_sync") as mock_run:
            mock_run.return_value = 100
            result = await target.verify("users", 100)

            assert result is True

    @pytest.mark.asyncio
    async def test_verify_fails_on_mismatch(self, target):
        """Test verify fails when count doesn't match."""
        with patch.object(target, "_run_sync") as mock_run:
            mock_run.return_value = 50
            with pytest.raises(ValidationFailedError):
                await target.verify("users", 100)


class TestDuckDBTargetTruncate:
    """Test truncate method."""

    @pytest.fixture
    def target(self):
        """Create DuckDBTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool._engine = mock_engine
        return DuckDBTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_truncate(self, target):
        """Test truncate executes."""
        with patch.object(target, "_run_sync") as mock_run:
            mock_run.return_value = None
            await target.truncate("users")


class TestDuckDBTargetRunSync:
    """Test _run_sync method."""

    @pytest.fixture
    def target(self):
        """Create DuckDBTarget with mock pool."""
        mock_pool = MagicMock()
        mock_engine = MagicMock()
        mock_pool._engine = mock_engine
        return DuckDBTarget(mock_pool)

    @pytest.mark.asyncio
    async def test_run_sync_executes_function(self, target):
        """Test _run_sync executes sync function."""

        def test_func():
            return "result"

        result = await target._run_sync(test_func)

        assert result == "result"
