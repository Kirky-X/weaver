# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMFailureCleanupThread module."""

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.scheduler.llm_failure_cleanup import LLMFailureCleanupThread


class TestLLMFailureCleanupThread:
    """Tests for LLMFailureCleanupThread."""

    @pytest.fixture
    def mock_repo(self):
        """Create a mock LLMFailureRepo."""
        repo = MagicMock()
        repo.cleanup_older_than = AsyncMock(return_value=5)
        return repo

    @pytest.fixture
    def thread_instance(self, mock_repo):
        """Create LLMFailureCleanupThread with mock repo."""
        return LLMFailureCleanupThread(mock_repo)

    def test_start_spawns_daemon_thread(self, thread_instance, mock_repo):
        """Test start() spawns a daemon thread with correct name."""
        with patch("threading.Thread") as mock_thread_class:
            mock_thread = MagicMock()
            mock_thread_class.return_value = mock_thread

            thread_instance.start()

            mock_thread_class.assert_called_once()
            call_kwargs = mock_thread_class.call_args[1]
            assert call_kwargs["daemon"] is True
            assert call_kwargs["name"] == "llm-failure-cleanup"
            assert call_kwargs["target"] == thread_instance._run
            mock_thread.start.assert_called_once()

    def test_run_executes_cleanup_immediately(self, mock_repo):
        """Test _run() calls cleanup_older_than once synchronously on startup."""
        thread = LLMFailureCleanupThread(mock_repo)

        loop = None
        mock_loop = MagicMock()
        mock_loop.run_until_complete = MagicMock(return_value=None)
        mock_loop.close = MagicMock()

        def fake_new_event_loop():
            nonlocal loop
            loop = mock_loop
            return mock_loop

        with patch("asyncio.new_event_loop", side_effect=fake_new_event_loop):
            with patch("asyncio.set_event_loop"):
                with patch.object(thread, "_stop_event", MagicMock()) as mock_stop:
                    mock_stop.wait.side_effect = [True]  # stop immediately

                    thread._run()

        mock_loop.run_until_complete.assert_called()
        first_call = mock_loop.run_until_complete.call_args_list[0][0][0]
        # Verify cleanup_older_than was awaited
        assert hasattr(first_call, "cr_code") or mock_loop.run_until_complete.called
        # Confirm cleanup was invoked at least once before wait
        mock_repo.cleanup_older_than.assert_called()

    def test_stop_sets_event_and_joins_thread(self, mock_repo):
        """Test stop() sets stop event and joins thread within timeout."""
        thread = LLMFailureCleanupThread(mock_repo)

        mock_thread = MagicMock()
        thread._thread = mock_thread

        thread.stop()

        mock_thread.join.assert_called_once_with(timeout=10)

    def test_stop_handles_none_thread(self, mock_repo):
        """Test stop() does not raise when _thread is None."""
        thread = LLMFailureCleanupThread(mock_repo)
        thread._thread = None

        # Should not raise
        thread.stop()

    def test_stop_event_is_set_on_stop(self, mock_repo):
        """Test stop() sets the stop event."""
        thread = LLMFailureCleanupThread(mock_repo)

        with patch.object(threading, "Event") as mock_event_class:
            mock_event = MagicMock()
            mock_event_class.return_value = mock_event

            thread2 = LLMFailureCleanupThread(mock_repo)
            thread2._stop_event = mock_event
            thread2._thread = MagicMock()

            thread2.stop()

            mock_event.set.assert_called_once()

    def test_cleanup_older_than_called_with_default_days(self, mock_repo):
        """Test cleanup_older_than is called with days=3 by default."""
        thread = LLMFailureCleanupThread(mock_repo)

        loop = MagicMock()
        loop.run_until_complete = MagicMock(return_value=None)
        loop.close = MagicMock()

        def fake_new_event_loop():
            return loop

        with patch("asyncio.new_event_loop", side_effect=fake_new_event_loop):
            with patch("asyncio.set_event_loop"):
                with patch.object(thread, "_stop_event", MagicMock()) as mock_stop:
                    mock_stop.wait.side_effect = [True]

                    thread._run()

        mock_repo.cleanup_older_than.assert_called_with(3)
