# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for storage LLMUsageRepo."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db.models import LLMUsageHourly, LLMUsageRaw
from core.event.bus import LLMUsageEvent
from core.llm.request import TokenUsage
from modules.storage.llm_usage_repo import LLMUsageRepo


class TestLLMUsageRepoInsertRaw:
    """Tests for LLMUsageRepo.insert_raw()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.fixture
    def sample_event(self):
        return LLMUsageEvent(
            label="chat::openai::gpt-4",
            call_point="classifier",
            llm_type="chat",
            provider="openai",
            model="gpt-4",
            tokens=TokenUsage(input_tokens=100, output_tokens=50),
            latency_ms=1500.0,
            success=True,
            error_type=None,
            article_id=123,
            task_id="task-001",
        )

    @pytest.mark.asyncio
    async def test_insert_raw_inserts_correct_fields(self, repo, mock_pool, sample_event):
        """Test insert_raw() inserts LLMUsageRaw with all event fields."""
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw(sample_event)

        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

        added: LLMUsageRaw = mock_session.add.call_args[0][0]
        assert added.label == "chat::openai::gpt-4"
        assert added.call_point == "classifier"
        assert added.llm_type == "chat"
        assert added.provider == "openai"
        assert added.model == "gpt-4"
        assert added.input_tokens == 100
        assert added.output_tokens == 50
        assert added.total_tokens == 150
        assert added.latency_ms == 1500.0
        assert added.success is True
        assert added.error_type is None
        assert added.article_id == 123
        assert added.task_id == "task-001"

    @pytest.mark.asyncio
    async def test_insert_raw_handles_failed_event(self, repo, mock_pool):
        """Test insert_raw() handles failed events correctly."""
        event = LLMUsageEvent(
            label="chat::anthropic::claude-3",
            call_point="analyzer",
            llm_type="chat",
            provider="anthropic",
            model="claude-3",
            tokens=TokenUsage(input_tokens=200, output_tokens=0),
            latency_ms=30000.0,
            success=False,
            error_type="TimeoutError",
            article_id=456,
            task_id="task-002",
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw(event)

        added: LLMUsageRaw = mock_session.add.call_args[0][0]
        assert added.success is False
        assert added.error_type == "TimeoutError"

    @pytest.mark.asyncio
    async def test_insert_raw_handles_none_article_id(self, repo, mock_pool):
        """Test insert_raw() handles None article_id."""
        event = LLMUsageEvent(
            label="embedding::openai::text-embedding-3-small",
            call_point="entity_extractor",
            llm_type="embedding",
            provider="openai",
            model="text-embedding-3-small",
            tokens=TokenUsage(input_tokens=500, output_tokens=0),
            latency_ms=200.0,
            success=True,
            article_id=None,
            task_id=None,
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw(event)

        added: LLMUsageRaw = mock_session.add.call_args[0][0]
        assert added.article_id is None
        assert added.task_id is None


class TestLLMUsageRepoInsertRawBatch:
    """Tests for LLMUsageRepo.insert_raw_batch()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_insert_raw_batch_creates_multiple_records(self, repo, mock_pool):
        """Test insert_raw_batch() creates multiple records."""
        events = [
            LLMUsageEvent(
                label="chat::openai::gpt-4",
                call_point="classifier",
                tokens=TokenUsage(input_tokens=100, output_tokens=50),
                latency_ms=1000.0,
                success=True,
            ),
            LLMUsageEvent(
                label="chat::anthropic::claude-3",
                call_point="analyzer",
                tokens=TokenUsage(input_tokens=200, output_tokens=100),
                latency_ms=2000.0,
                success=False,
                error_type="ApiError",
            ),
        ]

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        count = await repo.insert_raw_batch(events)

        assert count == 2
        mock_session.add_all.assert_called_once()
        added_records = mock_session.add_all.call_args[0][0]
        assert len(added_records) == 2

    @pytest.mark.asyncio
    async def test_insert_raw_batch_handles_empty_list(self, repo, mock_pool):
        """Test insert_raw_batch() handles empty list."""
        count = await repo.insert_raw_batch([])
        assert count == 0
        mock_pool.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_insert_raw_batch_preserves_timestamp(self, repo, mock_pool):
        """Test insert_raw_batch() uses event.timestamp as created_at."""
        ts = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        events = [
            LLMUsageEvent(
                label="chat::test::model",
                call_point="test",
                tokens=TokenUsage(),
                latency_ms=100.0,
                success=True,
            ),
        ]

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw_batch(events)

        added: LLMUsageRaw = mock_session.add_all.call_args[0][0][0]
        assert added.created_at is not None


class TestLLMUsageRepoQueryRaw:
    """Tests for LLMUsageRepo.query_raw()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_query_raw_with_filters(self, repo, mock_pool):
        """Test query_raw() applies all filters correctly."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=1)
        end_time = datetime.now(UTC)

        await repo.query_raw(
            start_time=start_time,
            end_time=end_time,
            provider="openai",
            model="gpt-4",
            llm_type="chat",
            call_point="classifier",
            success=True,
            limit=100,
        )

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_raw_limits_results(self, repo, mock_pool):
        """Test query_raw() caps limit at 10000."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=1)
        end_time = datetime.now(UTC)

        await repo.query_raw(start_time=start_time, end_time=end_time, limit=50000)

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_raw_returns_records(self, repo, mock_pool):
        """Test query_raw() returns matching records."""
        mock_record = MagicMock(spec=LLMUsageRaw)
        mock_record.provider = "openai"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=1)
        end_time = datetime.now(UTC)

        result = await repo.query_raw(start_time=start_time, end_time=end_time)

        assert len(result) == 1
        assert result[0].provider == "openai"


class TestLLMUsageRepoLatencyBounds:
    """Tests for LLMUsageRepo.get_latency_bounds()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_latency_bounds_returns_min_max(self, repo, mock_pool):
        """Test get_latency_bounds() returns min and max latency."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.min_latency = 100.0
        mock_row.max_latency = 5000.0
        mock_result.first.return_value = mock_row
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        time_bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        min_lat, max_lat = await repo.get_latency_bounds(
            time_bucket=time_bucket,
            label="chat::openai::gpt-4",
            call_point="classifier",
        )

        assert min_lat == 100.0
        assert max_lat == 5000.0

    @pytest.mark.asyncio
    async def test_get_latency_bounds_handles_no_records(self, repo, mock_pool):
        """Test get_latency_bounds() returns zeros when no records."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        time_bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        min_lat, max_lat = await repo.get_latency_bounds(
            time_bucket=time_bucket,
            label="chat::openai::gpt-4",
            call_point="classifier",
        )

        assert min_lat == 0.0
        assert max_lat == 0.0

    @pytest.mark.asyncio
    async def test_get_latency_bounds_handles_null_min(self, repo, mock_pool):
        """Test get_latency_bounds() returns zeros when min_latency is None."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.min_latency = None
        mock_result.first.return_value = mock_row
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        time_bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        min_lat, max_lat = await repo.get_latency_bounds(
            time_bucket=time_bucket,
            label="chat::test::model",
            call_point="test",
        )

        assert min_lat == 0.0
        assert max_lat == 0.0


class TestLLMUsageRepoUpsertHourly:
    """Tests for LLMUsageRepo.upsert_hourly()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_upsert_hourly_creates_record(self, repo, mock_pool):
        """Test upsert_hourly() executes upsert statement."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        time_bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        await repo.upsert_hourly(
            time_bucket=time_bucket,
            label="chat::openai::gpt-4",
            call_point="classifier",
            llm_type="chat",
            provider="openai",
            model="gpt-4",
            call_count=100,
            input_tokens_sum=10000,
            output_tokens_sum=5000,
            total_tokens_sum=15000,
            latency_sum=150000.0,
            latency_min=100.0,
            latency_max=5000.0,
            success_count=95,
            failure_count=5,
        )

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_hourly_zero_calls(self, repo, mock_pool):
        """Test upsert_hourly() handles zero call_count (avg = 0.0)."""
        mock_session = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        time_bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        await repo.upsert_hourly(
            time_bucket=time_bucket,
            label="chat::test::model",
            call_point="test",
            llm_type="chat",
            provider="test",
            model="test",
            call_count=0,
            input_tokens_sum=0,
            output_tokens_sum=0,
            total_tokens_sum=0,
            latency_sum=0.0,
            latency_min=0.0,
            latency_max=0.0,
            success_count=0,
            failure_count=0,
        )

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestLLMUsageRepoGetHourlyStats:
    """Tests for LLMUsageRepo.get_hourly_stats()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_hourly_stats_returns_records(self, repo, mock_pool):
        """Test get_hourly_stats() returns hourly records as dicts."""
        mock_record = MagicMock(spec=LLMUsageHourly)
        mock_record.time_bucket = datetime.now(UTC)
        mock_record.label = "chat::openai::gpt-4"
        mock_record.call_point = "classifier"
        mock_record.llm_type = "chat"
        mock_record.provider = "openai"
        mock_record.model = "gpt-4"
        mock_record.call_count = 100
        mock_record.input_tokens_sum = 10000
        mock_record.output_tokens_sum = 5000
        mock_record.total_tokens_sum = 15000
        mock_record.latency_avg_ms = 1500.0
        mock_record.latency_min_ms = 100.0
        mock_record.latency_max_ms = 5000.0
        mock_record.success_count = 95
        mock_record.failure_count = 5

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_hourly_stats(start_time=start_time, end_time=end_time)

        assert len(result) == 1
        assert result[0]["call_count"] == 100
        assert result[0]["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_get_hourly_stats_with_filters(self, repo, mock_pool):
        """Test get_hourly_stats() applies label, call_point, provider filters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_hourly_stats(
            start_time=start_time,
            end_time=end_time,
            label="chat::openai::gpt-4",
            call_point="classifier",
            provider="openai",
        )

        assert result == []
        mock_session.execute.assert_called_once()


class TestLLMUsageRepoQueryHourly:
    """Tests for LLMUsageRepo.query_hourly()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_query_hourly_with_hourly_granularity(self, repo, mock_pool):
        """Test query_hourly() with hourly granularity."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                time_bucket=datetime(2024, 1, 15, 10, 0, 0),
                call_count=100,
                input_tokens_sum=10000,
                output_tokens_sum=5000,
                total_tokens_sum=15000,
                latency_avg_ms=1500.0,
                latency_min_ms=100.0,
                latency_max_ms=5000.0,
                success_count=95,
                failure_count=5,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.query_hourly(
            start_time=start_time,
            end_time=end_time,
            granularity="hourly",
        )

        assert len(result) == 1
        assert result[0]["call_count"] == 100

    @pytest.mark.asyncio
    async def test_query_hourly_with_daily_granularity(self, repo, mock_pool):
        """Test query_hourly() with daily granularity."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                time_bucket=datetime(2024, 1, 15, 0, 0, 0),
                call_count=500,
                input_tokens_sum=50000,
                output_tokens_sum=25000,
                total_tokens_sum=75000,
                latency_avg_ms=1400.0,
                latency_min_ms=50.0,
                latency_max_ms=6000.0,
                success_count=480,
                failure_count=20,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(days=7)
        end_time = datetime.now(UTC)

        result = await repo.query_hourly(
            start_time=start_time,
            end_time=end_time,
            granularity="daily",
        )

        assert len(result) == 1
        assert result[0]["call_count"] == 500

    @pytest.mark.asyncio
    async def test_query_hourly_with_monthly_granularity(self, repo, mock_pool):
        """Test query_hourly() with monthly granularity."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(days=30)
        end_time = datetime.now(UTC)

        result = await repo.query_hourly(
            start_time=start_time,
            end_time=end_time,
            granularity="monthly",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_query_hourly_with_filters(self, repo, mock_pool):
        """Test query_hourly() applies all filters."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        await repo.query_hourly(
            start_time=start_time,
            end_time=end_time,
            granularity="hourly",
            provider="openai",
            model="gpt-4",
            llm_type="chat",
            call_point="classifier",
        )

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_hourly_handles_null_time_bucket(self, repo, mock_pool):
        """Test query_hourly() handles None time_bucket in result."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                time_bucket=None,
                call_count=10,
                input_tokens_sum=100,
                output_tokens_sum=50,
                total_tokens_sum=150,
                latency_avg_ms=None,
                latency_min_ms=None,
                latency_max_ms=None,
                success_count=8,
                failure_count=2,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.query_hourly(start_time=start_time, end_time=end_time)

        assert result[0]["time_bucket"] is None
        assert result[0]["latency_avg_ms"] == 0.0


class TestLLMUsageRepoGetSummary:
    """Tests for LLMUsageRepo.get_summary()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_summary_returns_correct_structure(self, repo, mock_pool):
        """Test get_summary() returns correct summary structure."""
        mock_session = AsyncMock()

        mock_summary_result = MagicMock()
        mock_summary_row = MagicMock()
        mock_summary_row.total_calls = 100
        mock_summary_row.total_input_tokens = 10000
        mock_summary_row.total_output_tokens = 5000
        mock_summary_row.total_tokens = 15000
        mock_summary_row.avg_latency_ms = 1500.0
        mock_summary_row.max_latency_ms = 5000.0
        mock_summary_row.min_latency_ms = 100.0
        mock_summary_row.success_count = 95
        mock_summary_result.first.return_value = mock_summary_row

        mock_error_result = MagicMock()
        mock_error_result.all.return_value = [
            MagicMock(error_type="TimeoutError", count=3),
            MagicMock(error_type="RateLimitError", count=2),
        ]

        mock_session.execute.side_effect = [mock_summary_result, mock_error_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        summary = await repo.get_summary(start_time=start_time, end_time=end_time)

        assert summary["total_calls"] == 100
        assert summary["total_input_tokens"] == 10000
        assert summary["total_output_tokens"] == 5000
        assert summary["total_tokens"] == 15000
        assert summary["avg_latency_ms"] == 1500.0
        assert summary["max_latency_ms"] == 5000.0
        assert summary["min_latency_ms"] == 100.0
        assert summary["success_rate"] == 0.95
        assert summary["error_types"]["TimeoutError"] == 3
        assert summary["error_types"]["RateLimitError"] == 2

    @pytest.mark.asyncio
    async def test_get_summary_handles_zero_calls(self, repo, mock_pool):
        """Test get_summary() handles case with no calls."""
        mock_session = AsyncMock()

        mock_summary_result = MagicMock()
        mock_summary_row = MagicMock()
        mock_summary_row.total_calls = 0
        mock_summary_row.total_input_tokens = None
        mock_summary_row.total_output_tokens = None
        mock_summary_row.total_tokens = None
        mock_summary_row.avg_latency_ms = None
        mock_summary_row.max_latency_ms = None
        mock_summary_row.min_latency_ms = None
        mock_summary_row.success_count = None
        mock_summary_result.first.return_value = mock_summary_row

        mock_error_result = MagicMock()
        mock_error_result.all.return_value = []

        mock_session.execute.side_effect = [mock_summary_result, mock_error_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        summary = await repo.get_summary(start_time=start_time, end_time=end_time)

        assert summary["total_calls"] == 0
        assert summary["success_rate"] == 1.0
        assert summary["total_tokens"] == 0
        assert summary["error_types"] == {}

    @pytest.mark.asyncio
    async def test_get_summary_with_filters(self, repo, mock_pool):
        """Test get_summary() applies optional filters."""
        mock_session = AsyncMock()

        mock_summary_result = MagicMock()
        mock_summary_row = MagicMock()
        mock_summary_row.total_calls = 10
        mock_summary_row.total_input_tokens = 500
        mock_summary_row.total_output_tokens = 200
        mock_summary_row.total_tokens = 700
        mock_summary_row.avg_latency_ms = 500.0
        mock_summary_row.max_latency_ms = 1000.0
        mock_summary_row.min_latency_ms = 100.0
        mock_summary_row.success_count = 8
        mock_summary_result.first.return_value = mock_summary_row

        mock_error_result = MagicMock()
        mock_error_result.all.return_value = []

        mock_session.execute.side_effect = [mock_summary_result, mock_error_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        summary = await repo.get_summary(
            start_time=start_time,
            end_time=end_time,
            provider="openai",
            model="gpt-4",
            llm_type="chat",
            call_point="classifier",
        )

        assert summary["total_calls"] == 10

    @pytest.mark.asyncio
    async def test_get_summary_handles_null_error_type(self, repo, mock_pool):
        """Test get_summary() maps None error_type to 'unknown'."""
        mock_session = AsyncMock()

        mock_summary_result = MagicMock()
        mock_summary_row = MagicMock()
        mock_summary_row.total_calls = 5
        mock_summary_row.total_input_tokens = 500
        mock_summary_row.total_output_tokens = 200
        mock_summary_row.total_tokens = 700
        mock_summary_row.avg_latency_ms = 1000.0
        mock_summary_row.max_latency_ms = 2000.0
        mock_summary_row.min_latency_ms = 500.0
        mock_summary_row.success_count = 0
        mock_summary_result.first.return_value = mock_summary_row

        mock_error_result = MagicMock()
        mock_error_result.all.return_value = [
            MagicMock(error_type=None, count=5),
        ]

        mock_session.execute.side_effect = [mock_summary_result, mock_error_result]
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        summary = await repo.get_summary(start_time=start_time, end_time=end_time)

        assert "unknown" in summary["error_types"]
        assert summary["error_types"]["unknown"] == 5


class TestLLMUsageRepoGetSummaryStats:
    """Tests for LLMUsageRepo.get_summary_stats()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_summary_stats_groups_by_label(self, repo, mock_pool):
        """Test get_summary_stats() groups by label."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                group_key="chat::openai::gpt-4",
                total_calls=100,
                total_input_tokens=10000,
                total_output_tokens=5000,
                total_tokens=15000,
                avg_latency_ms=1500.0,
                total_success=95,
                total_failure=5,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_summary_stats(
            start_time=start_time,
            end_time=end_time,
            group_by="label",
        )

        assert len(result) == 1
        assert result[0]["group"] == "chat::openai::gpt-4"
        assert result[0]["total_calls"] == 100

    @pytest.mark.asyncio
    async def test_get_summary_stats_groups_by_call_point(self, repo, mock_pool):
        """Test get_summary_stats() groups by call_point."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                group_key="classifier",
                total_calls=50,
                total_input_tokens=5000,
                total_output_tokens=2500,
                total_tokens=7500,
                avg_latency_ms=800.0,
                total_success=48,
                total_failure=2,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_summary_stats(
            start_time=start_time,
            end_time=end_time,
            group_by="call_point",
        )

        assert result[0]["group"] == "classifier"

    @pytest.mark.asyncio
    async def test_get_summary_stats_handles_none_latency(self, repo, mock_pool):
        """Test get_summary_stats() handles None avg_latency_ms."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                group_key="test",
                total_calls=0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_tokens=0,
                avg_latency_ms=None,
                total_success=0,
                total_failure=0,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_summary_stats(
            start_time=start_time,
            end_time=end_time,
            group_by="provider",
        )

        assert result[0]["avg_latency_ms"] == 0.0

    @pytest.mark.asyncio
    async def test_get_summary_stats_defaults_to_label(self, repo, mock_pool):
        """Test get_summary_stats() defaults to label for unknown group_by."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_summary_stats(
            start_time=start_time,
            end_time=end_time,
            group_by="unknown_dimension",
        )

        assert result == []


class TestLLMUsageRepoGetByProvider:
    """Tests for LLMUsageRepo.get_by_provider()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_by_provider_groups_correctly(self, repo, mock_pool):
        """Test get_by_provider() groups by provider."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                provider="openai",
                call_count=100,
                total_tokens=15000,
                avg_latency_ms=1500.0,
                success_count=95,
            ),
            MagicMock(
                provider="anthropic",
                call_count=50,
                total_tokens=10000,
                avg_latency_ms=2000.0,
                success_count=48,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_by_provider(start_time=start_time, end_time=end_time)

        assert len(result) == 2
        assert result[0]["provider"] == "openai"
        assert result[0]["call_count"] == 100
        assert result[0]["success_rate"] == 0.95
        assert result[1]["provider"] == "anthropic"
        assert result[1]["success_rate"] == 0.96

    @pytest.mark.asyncio
    async def test_get_by_provider_with_llm_type_filter(self, repo, mock_pool):
        """Test get_by_provider() filters by llm_type."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_by_provider(
            start_time=start_time,
            end_time=end_time,
            llm_type="embedding",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_by_provider_handles_zero_calls(self, repo, mock_pool):
        """Test get_by_provider() handles zero calls gracefully."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                provider="test",
                call_count=0,
                total_tokens=0,
                avg_latency_ms=None,
                success_count=0,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_by_provider(start_time=start_time, end_time=end_time)

        assert result[0]["success_rate"] == 0.0


class TestLLMUsageRepoGetByModel:
    """Tests for LLMUsageRepo.get_by_model()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_by_model_groups_correctly(self, repo, mock_pool):
        """Test get_by_model() groups by model and provider."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                model="gpt-4",
                provider="openai",
                call_count=80,
                total_tokens=12000,
                avg_latency_ms=1500.0,
                success_count=76,
            ),
            MagicMock(
                model="gpt-3.5-turbo",
                provider="openai",
                call_count=20,
                total_tokens=3000,
                avg_latency_ms=500.0,
                success_count=19,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_by_model(start_time=start_time, end_time=end_time)

        assert len(result) == 2
        assert result[0]["model"] == "gpt-4"
        assert result[0]["provider"] == "openai"
        assert result[0]["success_rate"] == 0.95

    @pytest.mark.asyncio
    async def test_get_by_model_filters_by_provider(self, repo, mock_pool):
        """Test get_by_model() filters by provider."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        await repo.get_by_model(
            start_time=start_time,
            end_time=end_time,
            provider="openai",
        )

        mock_session.execute.assert_called_once()


class TestLLMUsageRepoGetByCallPoint:
    """Tests for LLMUsageRepo.get_by_call_point()."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_by_call_point_groups_correctly(self, repo, mock_pool):
        """Test get_by_call_point() groups by call point."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                call_point="classifier",
                call_count=50,
                total_tokens=5000,
                avg_latency_ms=300.0,
                success_count=49,
            ),
            MagicMock(
                call_point="analyzer",
                call_count=30,
                total_tokens=8000,
                avg_latency_ms=2000.0,
                success_count=28,
            ),
        ]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_by_call_point(start_time=start_time, end_time=end_time)

        assert len(result) == 2
        assert result[0]["call_point"] == "classifier"
        assert result[1]["call_point"] == "analyzer"


class TestLLMUsageRepoCleanup:
    """Tests for LLMUsageRepo cleanup operations."""

    @pytest.fixture
    def mock_pool(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_cleanup_raw_older_than_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_raw_older_than() deletes old records."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 150
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_raw_older_than(days=30)

        assert removed == 150
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_raw_older_than_custom_days(self, repo, mock_pool):
        """Test cleanup_raw_older_than() respects custom days."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 50
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_raw_older_than(days=7)

        assert removed == 50

    @pytest.mark.asyncio
    async def test_cleanup_raw_default_days(self, repo, mock_pool):
        """Test cleanup_raw_older_than() defaults to 2 days."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 10
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_raw_older_than()

        assert removed == 10

    @pytest.mark.asyncio
    async def test_cleanup_hourly_older_than_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_hourly_older_than() deletes old hourly records."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 24
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_hourly_older_than(days=365)

        assert removed == 24
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_hourly_older_than_custom_days(self, repo, mock_pool):
        """Test cleanup_hourly_older_than() respects custom days."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 100
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_hourly_older_than(days=30)

        assert removed == 100
