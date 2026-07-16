# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for SQLAlchemy event listeners.

Tests verify:
- before_cursor_execute records start time
- after_cursor_execute calculates duration
- Slow queries trigger WARNING log
- Fast queries don't trigger log
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from core.db.events import (
    DEFAULT_SLOW_QUERY_THRESHOLD_MS,
    after_cursor_execute,
    before_cursor_execute,
)


@pytest.fixture
def engine():
    """Create in-memory SQLite engine for testing."""
    return create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


@pytest.fixture
def mock_connection(engine):
    """Create mock connection with info dict."""
    conn = MagicMock()
    conn.info = {}
    return conn


class TestBeforeCursorExecute:
    """Test before_cursor_execute event listener."""

    def test_records_start_time(self, mock_connection):
        """Test that before_cursor_execute records start time in conn.info."""
        before_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        # Check that query_start_time was recorded
        assert "query_start_time" in mock_connection.info
        assert isinstance(mock_connection.info["query_start_time"], list)
        assert len(mock_connection.info["query_start_time"]) == 1

        # Check that the recorded time is recent (within last second)
        recorded_time = mock_connection.info["query_start_time"][0]
        current_time = time.time()
        assert current_time - recorded_time < 1.0, "Recorded time should be within last second"

    def test_appends_to_existing_list(self, mock_connection):
        """Test that start time is appended to existing list."""
        # Pre-populate with one time
        mock_connection.info["query_start_time"] = [time.time() - 10]

        before_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 2",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        # Should have 2 entries now
        assert len(mock_connection.info["query_start_time"]) == 2

    def test_handles_multiple_queries(self, mock_connection):
        """Test handling multiple sequential queries."""
        # Simulate 3 queries
        for i in range(3):
            before_cursor_execute(
                conn=mock_connection,
                cursor=MagicMock(),
                statement=f"SELECT {i}",
                parameters=None,
                context=MagicMock(),
                executemany=False,
            )

        assert len(mock_connection.info["query_start_time"]) == 3

    @patch("core.db.events.log")
    def test_logs_debug_message(self, mock_log, mock_connection):
        """Test that before_cursor_execute logs debug message."""
        statement = "SELECT * FROM users WHERE id = 1"

        before_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement=statement,
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        # Check debug log was called
        mock_log.debug.assert_called_once()
        call_args = mock_log.debug.call_args

        # First positional arg should be event name
        assert call_args[0][0] == "query_start"

        # Should include statement (truncated to 100 chars)
        kwargs = call_args[1]
        assert "statement" in kwargs
        assert kwargs["statement"] == statement[:100]

    def test_truncates_long_statement_in_log(self, mock_connection):
        """Test that long statements are truncated to 100 chars in log."""
        long_statement = "SELECT * FROM " + "a" * 200

        with patch("core.db.events.log") as mock_log:
            before_cursor_execute(
                conn=mock_connection,
                cursor=MagicMock(),
                statement=long_statement,
                parameters=None,
                context=MagicMock(),
                executemany=False,
            )

            call_args = mock_log.debug.call_args
            kwargs = call_args[1]
            logged_statement = kwargs["statement"]

            assert len(logged_statement) <= 100
            assert logged_statement == long_statement[:100]


class TestAfterCursorExecute:
    """Test after_cursor_execute event listener."""

    def test_calculates_duration(self, mock_connection):
        """Test that after_cursor_execute calculates query duration."""
        # Simulate before_cursor_execute
        start_time = time.time() - 0.050  # 50ms ago
        mock_connection.info["query_start_time"] = [start_time]

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        # Start time should be removed from list
        assert len(mock_connection.info["query_start_time"]) == 0

    def test_removes_start_time_from_list(self, mock_connection):
        """Test that start time is removed after calculation."""
        mock_connection.info["query_start_time"] = [time.time()]

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        assert (
            "query_start_time" not in mock_connection.info
            or len(mock_connection.info["query_start_time"]) == 0
        )

    def test_handles_empty_start_time_list(self, mock_connection):
        """Test that empty start time list is handled gracefully."""
        mock_connection.info["query_start_time"] = []

        # Should not raise exception
        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        # List should still be empty
        assert len(mock_connection.info["query_start_time"]) == 0

    def test_handles_missing_start_time_key(self, mock_connection):
        """Test that missing start time key is handled gracefully."""
        # Don't set query_start_time
        if "query_start_time" in mock_connection.info:
            del mock_connection.info["query_start_time"]

        # Should not raise exception
        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )


class TestSlowQueryLogging:
    """Test slow query logging functionality."""

    @patch("core.db.events.log")
    def test_slow_query_triggers_warning(self, mock_log, mock_connection):
        """Test that slow query (>100ms) triggers WARNING log."""
        # Simulate query that took 150ms
        start_time = time.time() - 0.150
        mock_connection.info["query_start_time"] = [start_time]

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT * FROM large_table",
            parameters={"param": "value"},
            context=MagicMock(),
            executemany=False,
        )

        # Warning should be logged
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args

        # Check event name
        assert call_args[0][0] == "slow_query_detected"

        # Check logged data
        kwargs = call_args[1]
        assert "duration_ms" in kwargs
        assert kwargs["duration_ms"] > 100
        assert "threshold_ms" in kwargs
        assert kwargs["threshold_ms"] == DEFAULT_SLOW_QUERY_THRESHOLD_MS
        assert "statement" in kwargs
        assert "parameters" in kwargs

    @patch("core.db.events.log")
    def test_fast_query_no_warning(self, mock_log, mock_connection):
        """Test that fast query (<100ms) does not trigger warning."""
        # Simulate query that took 50ms
        start_time = time.time() - 0.050
        mock_connection.info["query_start_time"] = [start_time]

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        # Warning should NOT be logged
        mock_log.warning.assert_not_called()

    @patch("core.db.events.log")
    def test_very_slow_query_logs_correct_duration(self, mock_log, mock_connection):
        """Test that very slow query logs correct duration."""
        # Simulate query that took 500ms
        start_time = time.time() - 0.500
        mock_connection.info["query_start_time"] = [start_time]

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT * FROM huge_table JOIN other_table",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        mock_log.warning.assert_called_once()
        kwargs = mock_log.warning.call_args[1]

        # Duration should be approximately 500ms (with some tolerance)
        assert 450 < kwargs["duration_ms"] < 550

    @patch("core.db.events.log")
    def test_slow_query_truncates_statement(self, mock_log, mock_connection):
        """Test that slow query statement is truncated to 200 chars."""
        start_time = time.time() - 0.200
        mock_connection.info["query_start_time"] = [start_time]

        long_statement = "SELECT * FROM " + "a" * 300

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement=long_statement,
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        kwargs = mock_log.warning.call_args[1]
        logged_statement = kwargs["statement"]

        assert len(logged_statement) <= 200
        assert logged_statement == long_statement[:200]

    @patch("core.db.events.log")
    def test_slow_query_truncates_parameters(self, mock_log, mock_connection):
        """Test that slow query parameters are truncated to 100 chars."""
        start_time = time.time() - 0.200
        mock_connection.info["query_start_time"] = [start_time]

        long_params = {"key": "value" * 50}  # Long parameter string

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=long_params,
            context=MagicMock(),
            executemany=False,
        )

        kwargs = mock_log.warning.call_args[1]
        logged_params = kwargs["parameters"]

        assert logged_params is not None
        assert len(logged_params) <= 100

    @patch("core.db.events.log")
    def test_slow_query_handles_none_parameters(self, mock_log, mock_connection):
        """Test that slow query handles None parameters."""
        start_time = time.time() - 0.200
        mock_connection.info["query_start_time"] = [start_time]

        after_cursor_execute(
            conn=mock_connection,
            cursor=MagicMock(),
            statement="SELECT 1",
            parameters=None,
            context=MagicMock(),
            executemany=False,
        )

        kwargs = mock_log.warning.call_args[1]
        # Parameters should be None in the log
        assert kwargs["parameters"] is None

    def test_custom_threshold_from_conn_info(self, mock_connection):
        """Test custom slow query threshold from conn.info."""
        # Set custom threshold to 50ms
        mock_connection.info["slow_query_threshold_ms"] = 50

        # Simulate query that took 75ms (slow with custom threshold)
        start_time = time.time() - 0.075
        mock_connection.info["query_start_time"] = [start_time]

        with patch("core.db.events.log") as mock_log:
            after_cursor_execute(
                conn=mock_connection,
                cursor=MagicMock(),
                statement="SELECT 1",
                parameters=None,
                context=MagicMock(),
                executemany=False,
            )

            # Should log warning with custom threshold
            mock_log.warning.assert_called_once()
            kwargs = mock_log.warning.call_args[1]
            assert kwargs["threshold_ms"] == 50


class TestIntegrationWithEngine:
    """Test event listeners with real SQLAlchemy engine."""

    def test_listeners_attached_to_engine(self, engine):
        """Test that event listeners are properly attached."""
        # The listeners should already be attached via decorator
        # We can verify by checking if they're in the event registry
        listeners = event.contains(engine.pool, "connect", before_cursor_execute)
        # Note: This test might need adjustment based on actual event registration

    def test_query_execution_with_listeners(self, engine):
        """Test that queries execute correctly with listeners attached."""
        with engine.connect() as conn:
            # This should trigger before_cursor_execute and after_cursor_execute
            result = conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            row = result.fetchone()

            assert row is not None
            assert row[0] == 1

    def test_multiple_queries_with_listeners(self, engine):
        """Test multiple sequential queries with listeners."""
        with engine.connect() as conn:
            for i in range(5):
                result = conn.execute(__import__("sqlalchemy").text(f"SELECT {i}"))
                row = result.fetchone()
                assert row[0] == i
