# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMFailureCleanupThread."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLLMFailureCleanupThread:
    """Tests for LLMFailureCleanupThread."""

    @pytest.fixture
    def mock_repo(self):
        """Create mock LLMFailureRepo."""
        repo = MagicMock()
        repo.cleanup_older_than = AsyncMock(return_value=42)
        return repo

    @pytest.fixture
    def cleanup_thread(self, mock_repo):
        """Create cleanup thread instance."""
        from modules.analytics.llm_failure.cleanup import LLMFailureCleanupThread

        return LLMFailureCleanupThread(repo=mock_repo)

    def test_init_sets_repo(self, mock_repo):
        """Test cleanup thread initializes with repo."""
        from modules.analytics.llm_failure.cleanup import LLMFailureCleanupThread

        cleanup = LLMFailureCleanupThread(repo=mock_repo)

        assert cleanup._repo is mock_repo

    def test_start_creates_thread(self, cleanup_thread):
        """Test start() creates daemon thread."""
        cleanup_thread.start()

        assert cleanup_thread._thread is not None
        assert cleanup_thread._thread.daemon is True
        assert cleanup_thread._thread.name == "llm-failure-cleanup"

        cleanup_thread.stop()

    def test_stop_sets_event(self, cleanup_thread):
        """Test stop() sets stop event."""
        cleanup_thread.stop()

        assert cleanup_thread._stop_event.is_set()

    def test_stop_waits_for_thread(self, mock_repo):
        """Test stop() waits for thread termination."""
        from modules.analytics.llm_failure.cleanup import LLMFailureCleanupThread

        cleanup = LLMFailureCleanupThread(repo=mock_repo)
        cleanup.start()

        # Give thread time to start
        import time

        time.sleep(0.1)

        cleanup.stop()

        assert cleanup._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_cleanup_calls_repo(self, mock_repo):
        """Test _cleanup() calls repo.cleanup_older_than(3)."""
        from modules.analytics.llm_failure.cleanup import LLMFailureCleanupThread

        cleanup = LLMFailureCleanupThread(repo=mock_repo)

        await cleanup._repo.cleanup_older_than(3)

        mock_repo.cleanup_older_than.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_execute_cleanup_handles_runtime_error(self, mock_repo):
        """Test _execute_cleanup() handles RuntimeError gracefully."""
        from modules.analytics.llm_failure.cleanup import LLMFailureCleanupThread

        cleanup = LLMFailureCleanupThread(repo=mock_repo)

        # Create a mock loop that raises RuntimeError
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = RuntimeError("Event loop closed")

        # Should not raise
        cleanup._execute_cleanup(mock_loop)

    @pytest.mark.asyncio
    async def test_execute_cleanup_handles_exception(self, mock_repo):
        """Test _execute_cleanup() handles general exceptions gracefully."""
        from modules.analytics.llm_failure.cleanup import LLMFailureCleanupThread

        cleanup = LLMFailureCleanupThread(repo=mock_repo)

        # Create a mock loop that raises Exception
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = Exception("Connection closed")

        # Should not raise
        cleanup._execute_cleanup(mock_loop)
