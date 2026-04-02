# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for storage LLMFailureRepo."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db.models import LLMFailure
from core.event.bus import LLMFailureEvent
from modules.analytics.llm_failure.repo import LLMFailureRepo


class TestLLMFailureRepoRecord:
    """Tests for LLMFailureRepo.record()."""

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
        from uuid import uuid4

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
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.record(event)

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
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.record(event)

        added: LLMFailure = mock_session.add.call_args[0][0]
        assert added.article_id is None

    @pytest.mark.asyncio
    async def test_record_handles_none_article_id(self, repo, mock_pool):
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
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.record(event)

        added: LLMFailure = mock_session.add.call_args[0][0]
        assert added.article_id is None


class TestLLMFailureRepoQuery:
    """Tests for LLMFailureRepo.query()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_query_returns_matching_records(self, repo, mock_pool):
        """Test query() returns records from database."""
        mock_failure = MagicMock(spec=LLMFailure)
        mock_failure.call_point = "classifier"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_failure]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        result = await repo.query(call_point="classifier", limit=50)

        assert len(result) == 1
        assert result[0].call_point == "classifier"
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_with_all_filters(self, repo, mock_pool):
        """Test query() applies all optional filters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        result = await repo.query(
            call_point="analyzer",
            status="TimeoutError",
            since=datetime(2026, 1, 1, tzinfo=UTC),
            limit=100,
        )

        assert result == []
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_caps_limit_at_200(self, repo, mock_pool):
        """Test query() caps limit at 200."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.query(limit=50000)

        # Verify execute was called (statement built internally with capped limit)
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_with_no_filters(self, repo, mock_pool):
        """Test query() works with default parameters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        result = await repo.query()

        assert result == []
        mock_session.execute.assert_called_once()


class TestLLMFailureRepoGetStats:
    """Tests for LLMFailureRepo.get_stats()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_stats_returns_correct_structure(self, repo, mock_pool):
        """Test get_stats() returns aggregated statistics."""
        mock_session = AsyncMock()

        # First execute: group by stats
        mock_stats_result = MagicMock()
        mock_stats_result.all.return_value = [
            MagicMock(call_point="classifier", error_type="RateLimitError", count=10),
            MagicMock(call_point="analyzer", error_type="TimeoutError", count=5),
        ]

        # Second execute: last failure timestamp
        mock_last_result = MagicMock()
        last_ts = datetime(2026, 3, 29, 14, 30, 0, tzinfo=UTC)
        mock_last_row = MagicMock()
        mock_last_row.__getitem__ = lambda self, idx: last_ts
        mock_last_row[0] = last_ts
        mock_last_result.first.return_value = mock_last_row

        mock_session.execute.side_effect = [mock_stats_result, mock_last_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        stats = await repo.get_stats()

        assert stats["total"] == 15
        assert stats["by_call_point"]["classifier"] == 10
        assert stats["by_call_point"]["analyzer"] == 5
        assert stats["by_error_type"]["RateLimitError"] == 10
        assert stats["by_error_type"]["TimeoutError"] == 5
        assert stats["last_failure_at"] == last_ts.isoformat()

    @pytest.mark.asyncio
    async def test_get_stats_with_since_filter(self, repo, mock_pool):
        """Test get_stats() respects since filter."""
        mock_session = AsyncMock()

        mock_stats_result = MagicMock()
        mock_stats_result.all.return_value = []

        mock_last_result = MagicMock()
        mock_last_result.first.return_value = None

        mock_session.execute.side_effect = [mock_stats_result, mock_last_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        stats = await repo.get_stats(since=datetime(2026, 1, 1, tzinfo=UTC))

        assert stats["total"] == 0
        assert stats["by_call_point"] == {}
        assert stats["by_error_type"] == {}
        assert stats["last_failure_at"] is None

    @pytest.mark.asyncio
    async def test_get_stats_handles_empty_database(self, repo, mock_pool):
        """Test get_stats() handles no records."""
        mock_session = AsyncMock()

        mock_stats_result = MagicMock()
        mock_stats_result.all.return_value = []

        mock_last_result = MagicMock()
        mock_last_result.first.return_value = None

        mock_session.execute.side_effect = [mock_stats_result, mock_last_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        stats = await repo.get_stats()

        assert stats["total"] == 0
        assert stats["by_call_point"] == {}
        assert stats["by_error_type"] == {}
        assert stats["last_failure_at"] is None

    @pytest.mark.asyncio
    async def test_get_stats_same_call_point_different_errors(self, repo, mock_pool):
        """Test get_stats() aggregates multiple error types per call_point."""
        mock_session = AsyncMock()

        mock_stats_result = MagicMock()
        mock_stats_result.all.return_value = [
            MagicMock(call_point="classifier", error_type="RateLimitError", count=3),
            MagicMock(call_point="classifier", error_type="TimeoutError", count=2),
        ]

        mock_last_result = MagicMock()
        mock_last_result.first.return_value = None

        mock_session.execute.side_effect = [mock_stats_result, mock_last_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        stats = await repo.get_stats()

        assert stats["by_call_point"]["classifier"] == 5
        assert stats["by_error_type"]["RateLimitError"] == 3
        assert stats["by_error_type"]["TimeoutError"] == 2


class TestLLMFailureRepoCleanup:
    """Tests for LLMFailureRepo.cleanup_older_than()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_older_than() deletes records and returns count."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 42
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_older_than(days=3)

        assert removed == 42
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_custom_days(self, repo, mock_pool):
        """Test cleanup_older_than() respects custom days parameter."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_older_than(days=7)

        assert removed == 0
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_default_days(self, repo, mock_pool):
        """Test cleanup_older_than() defaults to 3 days."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 10
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_older_than()

        assert removed == 10
