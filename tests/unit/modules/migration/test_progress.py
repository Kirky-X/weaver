# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.migration.progress module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from modules.migration.progress import (
    MigrationProgressDisplay,
    TaskInfo,
    format_duration,
)


class TestTaskInfo:
    """Test TaskInfo dataclass."""

    def test_create_task_info(self):
        """Test creating TaskInfo."""
        info = TaskInfo(
            name="test_table",
            total=100,
        )

        assert info.name == "test_table"
        assert info.total == 100
        assert info.migrated == 0
        assert info.completed is False
        assert info.failed is False

    def test_task_info_with_values(self):
        """Test TaskInfo with values."""
        info = TaskInfo(
            name="test_table",
            total=100,
            migrated=50,
            started_at=datetime.now(UTC),
            completed=True,
        )

        assert info.migrated == 50
        assert info.completed is True


class TestMigrationProgressDisplay:
    """Test MigrationProgressDisplay class."""

    def test_init(self):
        """Test initialization."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        assert display._source_db == "postgres"
        assert display._target_db == "duckdb"
        assert display._is_graph is False

    def test_init_with_console(self):
        """Test initialization with custom console."""
        mock_console = MagicMock()
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
            console=mock_console,
        )

        assert display._console is mock_console

    def test_start(self):
        """Test start method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.start()

        assert display._started_at is not None

    def test_stop(self):
        """Test stop method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.start()
        display.stop()

        # Should not raise

    def test_add_table(self):
        """Test add_table method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.add_table("test_table", 100)

        assert "test_table" in display._tasks
        assert "test_table" in display._task_info
        assert display._task_info["test_table"].total == 100

    def test_update(self):
        """Test update method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.add_table("test_table", 100)
        display.update("test_table", 10)

        assert display._task_info["test_table"].migrated == 10

    def test_complete(self):
        """Test complete method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.add_table("test_table", 100)
        display.complete("test_table")

        assert display._task_info["test_table"].completed is True

    def test_fail(self):
        """Test fail method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.add_table("test_table", 100)
        display.fail("test_table", "Test error")

        assert display._task_info["test_table"].failed is True
        assert display._task_info["test_table"].error == "Test error"

    def test_cancel(self):
        """Test cancel method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.add_table("test_table", 100)
        display.cancel("test_table")

        # Should not raise

    def test_get_progress_dict(self):
        """Test get_progress_dict method."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        display.add_table("test_table", 100)
        display.update("test_table", 50)

        result = display.get_progress_dict()

        assert "test_table" in result
        assert result["test_table"]["total"] == 100
        assert result["test_table"]["migrated"] == 50
        assert result["test_table"]["percent"] == 50.0

    def test_get_progress_dict_empty(self):
        """Test get_progress_dict when empty."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        result = display.get_progress_dict()

        assert result == {}

    def test_get_icon_relational(self):
        """Test _get_icon for relational migration."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        icon = display._get_icon("articles")

        assert icon == " "

    def test_get_icon_graph_entity(self):
        """Test _get_icon for graph entity nodes."""
        display = MigrationProgressDisplay(
            source_db="neo4j",
            target_db="ladybug",
            is_graph=True,
        )

        icon = display._get_icon("Entity")

        assert icon == "●"

    def test_get_icon_graph_other(self):
        """Test _get_icon for graph other nodes."""
        display = MigrationProgressDisplay(
            source_db="neo4j",
            target_db="ladybug",
            is_graph=True,
        )

        icon = display._get_icon("SomeLabel")

        assert icon == "○"


class TestFormatDuration:
    """Test format_duration function."""

    def test_seconds_only(self):
        """Test formatting seconds only."""
        result = format_duration(45.0)
        assert result == "45s"

    def test_minutes_and_seconds(self):
        """Test formatting minutes and seconds."""
        result = format_duration(90.0)
        assert result == "1m 30s"

    def test_hours_and_minutes(self):
        """Test formatting hours and minutes."""
        result = format_duration(3661.0)
        assert result == "1h 1m"

    def test_multiple_hours(self):
        """Test formatting multiple hours."""
        result = format_duration(7325.0)  # 2h 2m 5s
        assert result == "2h 2m"

    def test_zero_seconds(self):
        """Test formatting zero seconds."""
        result = format_duration(0.0)
        assert result == "0s"


class TestMigrationProgressDisplayIntegration:
    """Integration tests for MigrationProgressDisplay."""

    def test_full_workflow(self):
        """Test full workflow of progress display."""
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
        )

        # Add multiple tables
        display.add_table("users", 1000)
        display.add_table("articles", 5000)
        display.add_table("entities", 2000)

        # Update progress
        display.update("users", 100)
        display.update("users", 200)
        display.update("articles", 500)

        # Complete one
        display.complete("users")

        # Fail one
        display.fail("entities", "Connection lost")

        # Get final status
        result = display.get_progress_dict()

        assert result["users"]["completed"] is True
        assert result["users"]["migrated"] == 300
        assert result["articles"]["migrated"] == 500
        assert result["entities"]["failed"] is True
        assert result["entities"]["error"] == "Connection lost"

    def test_print_summary_empty(self):
        """Test print_summary with no tasks."""
        mock_console = MagicMock()
        display = MigrationProgressDisplay(
            source_db="postgres",
            target_db="duckdb",
            is_graph=False,
            console=mock_console,
        )

        display.print_summary()

        # Should not raise
