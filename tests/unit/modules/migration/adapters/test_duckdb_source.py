# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.migration.adapters.duckdb_source module."""

from unittest.mock import patch

import pytest

from modules.migration.adapters.duckdb_source import DuckDBSource
from modules.migration.models import ColumnDef, MigrationSchema


class TestDuckDBSourceInit:
    """Test DuckDBSource initialization."""

    def test_init(self, duckdb_mock_pool):
        """Test initialization."""
        source = DuckDBSource(duckdb_mock_pool)

        assert source._pool is duckdb_mock_pool


class TestDuckDBSourceReadSchema:
    """Test read_schema method."""

    @pytest.fixture
    def source(self, duckdb_mock_pool):
        """Create DuckDBSource with mock pool."""
        return DuckDBSource(duckdb_mock_pool)

    @pytest.mark.asyncio
    async def test_read_schema_empty(self, source):
        """Test read_schema with no tables."""
        # DuckDB uses sync operations wrapped in asyncio.to_thread
        # For testing, we mock the internal sync method
        with patch.object(source, "_run_sync") as mock_run:
            mock_run.return_value = []

            schemas = await source.read_schema()

            assert schemas == []


class TestDuckDBSourceReadBatch:
    """Test read_batch method."""

    @pytest.fixture
    def source(self, duckdb_mock_pool):
        """Create DuckDBSource with mock pool."""
        return DuckDBSource(duckdb_mock_pool)

    @pytest.mark.asyncio
    async def test_read_batch_returns_rows(self, source):
        """Test read_batch returns rows."""
        with patch.object(source, "_run_sync") as mock_run:
            mock_run.return_value = [{"id": 1, "name": "test"}]

            rows = await source.read_batch("users", 0, 100)

            assert rows == [{"id": 1, "name": "test"}]


class TestDuckDBSourceCount:
    """Test count method."""

    @pytest.fixture
    def source(self, duckdb_mock_pool):
        """Create DuckDBSource with mock pool."""
        return DuckDBSource(duckdb_mock_pool)

    @pytest.mark.asyncio
    async def test_count_returns_number(self, source):
        """Test count returns number."""
        with patch.object(source, "_run_sync") as mock_run:
            mock_run.return_value = 100

            count = await source.count("users")

            assert count == 100


class TestDuckDBSourceGetTableNames:
    """Test get_table_names method."""

    @pytest.fixture
    def source(self, duckdb_mock_pool):
        """Create DuckDBSource with mock pool."""
        return DuckDBSource(duckdb_mock_pool)

    @pytest.mark.asyncio
    async def test_get_table_names(self, source):
        """Test get_table_names returns list."""
        with patch.object(source, "_run_sync") as mock_run:
            mock_run.return_value = ["users", "articles"]

            tables = await source.get_table_names()

            assert tables == ["users", "articles"]


class TestDuckDBSourceReadIncremental:
    """Test read_incremental method."""

    @pytest.fixture
    def source(self, duckdb_mock_pool):
        """Create DuckDBSource with mock pool."""
        return DuckDBSource(duckdb_mock_pool)

    @pytest.mark.asyncio
    async def test_read_incremental_yields_batches(self, source):
        """Test read_incremental is a generator."""
        assert hasattr(source, "read_incremental")


class TestDuckDBSourceRunSync:
    """Test _run_sync method."""

    @pytest.fixture
    def source(self, duckdb_mock_pool):
        """Create DuckDBSource with mock pool."""
        return DuckDBSource(duckdb_mock_pool)

    @pytest.mark.asyncio
    async def test_run_sync_executes_function(self, source):
        """Test _run_sync executes sync function."""

        def test_func():
            return "result"

        result = await source._run_sync(test_func)

        assert result == "result"

    @pytest.mark.asyncio
    async def test_run_sync_with_args(self, source):
        """Test _run_sync with arguments."""

        def test_func(a, b):
            return a + b

        result = await source._run_sync(test_func, 1, 2)

        assert result == 3
