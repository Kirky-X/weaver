# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for analytics LLMFailureRepo."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestAnalyticsLLMFailureRepoRecord:
    """Tests for analytics LLMFailureRepo.record()."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool."""
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        """Create LLMFailureRepo with mock pool."""
        from modules.analytics.llm_failure.repo import LLMFailureRepo

        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_record_with_valid_uuid(self, repo, mock_pool):
        """Test record() with valid UUID."""
        from uuid import uuid4

        from core.event.bus import LLMFailureEvent

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

    @pytest.mark.asyncio
    async def test_record_with_invalid_uuid(self, repo, mock_pool):
        """Test record() with invalid UUID string."""
        from core.event.bus import LLMFailureEvent

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

        added = mock_session.add.call_args[0][0]
        assert added.article_id is None

    @pytest.mark.asyncio
    async def test_record_with_none_article_id(self, repo, mock_pool):
        """Test record() with None article_id."""
        from core.event.bus import LLMFailureEvent

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

        added = mock_session.add.call_args[0][0]
        assert added.article_id is None


class TestAnalyticsLLMFailureRepoQuery:
    """Tests for analytics LLMFailureRepo.query()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        from modules.analytics.llm_failure.repo import LLMFailureRepo

        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_query_with_filters(self, repo, mock_pool):
        """Test query() with filters."""
        from core.db.models import LLMFailure

        mock_failure = MagicMock(spec=LLMFailure)
        mock_failure.call_point = "classifier"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_failure]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        result = await repo.query(
            call_point="classifier",
            status="RateLimitError",
            since=datetime(2026, 1, 1, tzinfo=UTC),
            limit=50,
        )

        assert len(result) == 1
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_caps_limit(self, repo, mock_pool):
        """Test query() caps limit at 200."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.query(limit=50000)

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_without_filters(self, repo, mock_pool):
        """Test query() without filters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        result = await repo.query()

        assert result == []
        mock_session.execute.assert_called_once()


class TestAnalyticsLLMFailureRepoGetStats:
    """Tests for analytics LLMFailureRepo.get_stats()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        from modules.analytics.llm_failure.repo import LLMFailureRepo

        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_stats_returns_structure(self, repo, mock_pool):
        """Test get_stats() returns correct structure."""
        mock_session = AsyncMock()

        mock_stats_result = MagicMock()
        mock_stats_result.all.return_value = [
            MagicMock(call_point="classifier", error_type="RateLimitError", count=10),
            MagicMock(call_point="analyzer", error_type="TimeoutError", count=5),
        ]

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
        assert stats["by_error_type"]["RateLimitError"] == 10

    @pytest.mark.asyncio
    async def test_get_stats_with_since_filter(self, repo, mock_pool):
        """Test get_stats() with since filter."""
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

    @pytest.mark.asyncio
    async def test_get_stats_empty_database(self, repo, mock_pool):
        """Test get_stats() with empty database."""
        mock_session = AsyncMock()

        mock_stats_result = MagicMock()
        mock_stats_result.all.return_value = []

        mock_last_result = MagicMock()
        mock_last_result.first.return_value = None

        mock_session.execute.side_effect = [mock_stats_result, mock_last_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        stats = await repo.get_stats()

        assert stats["total"] == 0
        assert stats["last_failure_at"] is None


class TestAnalyticsLLMFailureRepoCleanup:
    """Tests for analytics LLMFailureRepo.cleanup_older_than()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        from modules.analytics.llm_failure.repo import LLMFailureRepo

        return LLMFailureRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_older_than() deletes records."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 42
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_older_than(days=3)

        assert removed == 42
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_custom_days(self, repo, mock_pool):
        """Test cleanup_older_than() with custom days."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 10
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_older_than(days=7)

        assert removed == 10

    @pytest.mark.asyncio
    async def test_cleanup_default_days(self, repo, mock_pool):
        """Test cleanup_older_than() with default days."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_older_than()

        assert removed == 5
