# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMFailureRepo module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core.db.models import LLMFailure
from core.event.bus import LLMFailureEvent
from modules.analytics.llm_failure.repo import LLMFailureRepo


class TestLLMFailureRepo:
    """Tests for LLMFailureRepo."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool."""
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        """Create LLMFailureRepo with mock pool."""
        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_record_inserts_correct_fields(self, repo, mock_pool):
        """Test record() inserts LLMFailure with all event fields."""
        article_id = str(uuid4())
        event = LLMFailureEvent(
            call_point="classifier",
            provider="openai",
            error_type="RateLimitError",
            error_detail="Rate limit exceeded",
            latency_ms=1500.0,
            article_id=article_id,
            task_id="task-123",
            attempt=1,
            fallback_tried=True,
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.record(event)

        mock_pool.session.assert_called_once()
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

        added: LLMFailure = mock_session.add.call_args[0][0]
        assert added.call_point == "classifier"
        assert added.provider == "openai"
        assert added.error_type == "RateLimitError"
        assert added.error_detail == "Rate limit exceeded"
        assert added.latency_ms == 1500.0
        assert str(added.article_id) == article_id
        assert added.task_id == "task-123"
        assert added.attempt == 1
        assert added.fallback_tried is True

    @pytest.mark.asyncio
    async def test_record_converts_invalid_uuid_to_none(self, repo, mock_pool):
        """Test record() sets article_id to None for invalid UUID strings."""
        event = LLMFailureEvent(
            call_point="analyzer",
            provider="anthropic",
            error_type="ApiError",
            error_detail="Invalid key",
            latency_ms=500.0,
            article_id="not-a-valid-uuid",
            task_id="task-456",
            attempt=0,
            fallback_tried=False,
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.record(event)

        added: LLMFailure = mock_session.add.call_args[0][0]
        assert added.article_id is None

    @pytest.mark.asyncio
    async def test_record_handles_missing_article_id(self, repo, mock_pool):
        """Test record() handles None article_id."""
        event = LLMFailureEvent(
            call_point="cleaner",
            provider="openai",
            error_type="TimeoutError",
            error_detail="Request timed out",
            latency_ms=30000.0,
            article_id=None,
            task_id="task-789",
            attempt=2,
            fallback_tried=True,
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.record(event)

        added: LLMFailure = mock_session.add.call_args[0][0]
        assert added.article_id is None
        assert added.task_id == "task-789"

    @pytest.mark.asyncio
    async def test_cleanup_older_than_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_older_than() deletes records older than cutoff and returns count."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 42
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_older_than(days=3)

        mock_pool.session.assert_called_once()
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        assert removed == 42

    @pytest.mark.asyncio
    async def test_cleanup_older_than_custom_days(self, repo, mock_pool):
        """Test cleanup_older_than() respects custom days parameter."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.cleanup_older_than(days=7)

        mock_session.execute.assert_called_once()
        assert mock_session.commit.call_count == 1
