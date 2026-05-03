# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.migration.engine module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.migration.engine import MigrationEngine
from modules.migration.exceptions import MigrationError, UnsupportedDatabaseError
from modules.migration.mapping_registry import MappingRegistry
from modules.migration.models import MigrationConfig, MigrationProgress, MigrationResult


class TestMigrationEngineInit:
    """Test MigrationEngine initialization."""

    def test_init_with_config(self):
        """Test initialization with config."""
        config = MigrationConfig(
            source_db="postgres",
            target_db="duckdb",
        )
        mock_container = MagicMock()

        engine = MigrationEngine(config, mock_container)

        assert engine._config is config
        assert engine._container is mock_container

    def test_init_with_mapping_registry(self):
        """Test initialization with mapping registry."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        mock_registry = MagicMock()

        engine = MigrationEngine(config, mock_container, mapping_registry=mock_registry)

        assert engine._mapping_registry is mock_registry

    def test_init_creates_default_mapping_registry(self):
        """Test creates default mapping registry."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()

        engine = MigrationEngine(config, mock_container)

        assert isinstance(engine._mapping_registry, MappingRegistry)


class TestIsGraphMigration:
    """Test _is_graph_migration method."""

    def test_relational_migration(self):
        """Test relational migration detection."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        assert engine._is_graph_migration() is False

    def test_graph_migration_from_neo4j(self):
        """Test graph migration detection from Neo4j."""
        config = MigrationConfig(source_db="neo4j", target_db="ladybug")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        assert engine._is_graph_migration() is True

    def test_graph_migration_to_neo4j(self):
        """Test graph migration detection to Neo4j."""
        config = MigrationConfig(source_db="duckdb", target_db="neo4j")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        assert engine._is_graph_migration() is True


class TestCreateRelationalSource:
    """Test _create_relational_source method."""

    def test_create_postgres_source(self):
        """Test creating PostgresSource."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        mock_pool = MagicMock()
        mock_container.relational_pool = mock_pool
        engine = MigrationEngine(config, mock_container)

        with patch("modules.migration.engine.PostgresSource") as mock_source:
            engine._create_relational_source()
            mock_source.assert_called_once_with(mock_pool)

    def test_create_duckdb_source(self):
        """Test creating DuckDBSource."""
        config = MigrationConfig(source_db="duckdb", target_db="postgres")
        mock_container = MagicMock()
        mock_pool = MagicMock()
        mock_container.duckdb_pool = mock_pool
        engine = MigrationEngine(config, mock_container)

        with patch("modules.migration.engine.DuckDBSource") as mock_source:
            engine._create_relational_source()
            mock_source.assert_called_once_with(mock_pool)

    def test_unsupported_source_raises_error(self):
        """Test unsupported source raises error."""
        config = MigrationConfig(source_db="invalid", target_db="duckdb")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        with pytest.raises(UnsupportedDatabaseError):
            engine._create_relational_source()


class TestCreateRelationalTarget:
    """Test _create_relational_target method."""

    def test_create_postgres_target(self):
        """Test creating PostgresTarget."""
        config = MigrationConfig(source_db="duckdb", target_db="postgres")
        mock_container = MagicMock()
        mock_pool = MagicMock()
        mock_container.relational_pool = mock_pool
        engine = MigrationEngine(config, mock_container)

        with patch("modules.migration.engine.PostgresTarget") as mock_target:
            engine._create_relational_target()
            mock_target.assert_called_once_with(mock_pool)

    def test_create_duckdb_target(self):
        """Test creating DuckDBTarget."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        mock_pool = MagicMock()
        mock_container.duckdb_pool = mock_pool
        engine = MigrationEngine(config, mock_container)

        with patch("modules.migration.engine.DuckDBTarget") as mock_target:
            engine._create_relational_target()
            mock_target.assert_called_once_with(mock_pool)

    def test_unsupported_target_raises_error(self):
        """Test unsupported target raises error."""
        config = MigrationConfig(source_db="postgres", target_db="invalid")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        with pytest.raises(UnsupportedDatabaseError):
            engine._create_relational_target()


class TestCreateGraphSource:
    """Test _create_graph_source method."""

    def test_create_neo4j_source(self):
        """Test creating Neo4jSource."""
        config = MigrationConfig(source_db="neo4j", target_db="ladybug")
        mock_container = MagicMock()
        mock_pool = MagicMock()
        mock_container.graph_pool = mock_pool
        engine = MigrationEngine(config, mock_container)

        with patch("modules.migration.engine.Neo4jSource") as mock_source:
            engine._create_graph_source()
            mock_source.assert_called_once_with(mock_pool)

    def test_create_ladybug_source(self):
        """Test creating LadybugSource."""
        config = MigrationConfig(source_db="ladybug", target_db="neo4j")
        mock_container = MagicMock()
        mock_pool = MagicMock()
        mock_container.ladybug_pool = mock_pool
        engine = MigrationEngine(config, mock_container)

        with patch("modules.migration.engine.LadybugSource") as mock_source:
            engine._create_graph_source()
            mock_source.assert_called_once_with(mock_pool)


class TestRun:
    """Test run method."""

    @pytest.fixture
    def engine(self):
        """Create MigrationEngine with mocks."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        return MigrationEngine(config, mock_container)

    @pytest.mark.asyncio
    async def test_run_relational_migration(self, engine):
        """Test running relational migration."""
        mock_source = AsyncMock()
        mock_source.get_table_names = AsyncMock(return_value=["table1"])
        mock_source.count = AsyncMock(return_value=100)
        mock_source.read_schema = AsyncMock(return_value=[])
        mock_source.read_batch = AsyncMock(return_value=[{"id": 1}])

        mock_target = AsyncMock()
        mock_target.ensure_schema = AsyncMock()
        mock_target.write_batch = AsyncMock(return_value=1)

        engine._create_relational_source = MagicMock(return_value=mock_source)
        engine._create_relational_target = MagicMock(return_value=mock_target)

        with patch("modules.migration.engine.MigrationProgressDisplay"):
            result = await engine.run()

        assert isinstance(result, MigrationResult)
        assert result.config is engine._config

    @pytest.mark.asyncio
    async def test_run_with_cancellation(self, engine):
        """Test running migration with cancellation."""
        mock_source = AsyncMock()
        mock_source.get_table_names = AsyncMock(return_value=["table1"])
        mock_source.count = AsyncMock(return_value=100)
        mock_source.read_schema = AsyncMock(return_value=[])
        mock_source.read_batch = AsyncMock(return_value=[{"id": 1}])

        mock_target = AsyncMock()
        mock_target.ensure_schema = AsyncMock()
        mock_target.write_batch = AsyncMock(return_value=1)

        engine._create_relational_source = MagicMock(return_value=mock_source)
        engine._create_relational_target = MagicMock(return_value=mock_target)

        engine.cancel()

        with patch("modules.migration.engine.MigrationProgressDisplay"):
            result = await engine.run()

        # Migration should be cancelled
        assert engine._cancelled is True


class TestCancel:
    """Test cancel method."""

    def test_cancel_sets_flag(self):
        """Test cancel sets cancelled flag."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        engine.cancel()

        assert engine._cancelled is True


class TestGetProgress:
    """Test get_progress method."""

    def test_get_progress_empty(self):
        """Test get_progress when empty."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        progress = engine.get_progress()

        assert progress == {}

    def test_get_progress_with_items(self):
        """Test get_progress with items."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        # Add progress item
        engine._progress["table1"] = MigrationProgress(
            table="table1",
            total=100,
            migrated=50,
        )

        progress = engine.get_progress()

        assert "table1" in progress
        assert progress["table1"].total == 100
        assert progress["table1"].migrated == 50


class TestGetProgressDict:
    """Test get_progress_dict method."""

    def test_get_progress_dict_without_display(self):
        """Test get_progress_dict without display."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        mock_container = MagicMock()
        engine = MigrationEngine(config, mock_container)

        result = engine.get_progress_dict()

        assert result == {}


class TestMigrationProgress:
    """Test MigrationProgress model."""

    def test_progress_properties(self):
        """Test progress properties."""
        progress = MigrationProgress(
            table="test_table",
            total=100,
            migrated=50,
            status="running",
        )

        assert progress.percent_complete == 50.0
        assert progress.elapsed_seconds >= 0

    def test_progress_zero_total(self):
        """Test progress with zero total."""
        progress = MigrationProgress(
            table="test_table",
            total=0,
            migrated=0,
        )

        assert progress.percent_complete == 0.0


class TestMigrationResult:
    """Test MigrationResult model."""

    def test_result_properties(self):
        """Test result properties."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        result = MigrationResult(
            config=config,
            items=[],
            started_at=datetime.now(),
            completed_at=datetime.now(),
            status="completed",
            total_migrated=100,
            total_expected=100,
        )

        assert result.success is True
        assert result.elapsed_seconds >= 0

    def test_result_partial_status(self):
        """Test result with partial status."""
        config = MigrationConfig(source_db="postgres", target_db="duckdb")
        result = MigrationResult(
            config=config,
            items=[],
            started_at=datetime.now(),
            status="partial",
        )

        assert result.success is False
