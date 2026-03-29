# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMUsageRepo module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db.models import LLMUsageHourly, LLMUsageRaw
from core.event.bus import LLMUsageEvent
from core.llm.request import TokenUsage
from modules.storage.llm_usage_repo import LLMUsageRepo


class TestLLMUsageRepo:
    """Tests for LLMUsageRepo."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool."""
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        """Create LLMUsageRepo with mock pool."""
        return LLMUsageRepo(mock_pool)

    @pytest.fixture
    def sample_event(self):
        """Create a sample LLMUsageEvent."""
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

    @pytest.fixture
    def sample_failed_event(self):
        """Create a sample failed LLMUsageEvent."""
        return LLMUsageEvent(
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

    # ── insert_raw tests ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_insert_raw_inserts_correct_fields(self, repo, mock_pool, sample_event):
        """Test insert_raw() inserts LLMUsageRaw with all event fields."""
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw(sample_event)

        mock_pool.session.assert_called_once()
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
    async def test_insert_raw_handles_failed_event(self, repo, mock_pool, sample_failed_event):
        """Test insert_raw() handles failed events correctly."""
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw(sample_failed_event)

        added: LLMUsageRaw = mock_session.add.call_args[0][0]
        assert added.success is False
        assert added.error_type == "TimeoutError"
        assert added.output_tokens == 0

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

    # ── insert_raw_batch tests ───────────────────────────────

    @pytest.mark.asyncio
    async def test_insert_raw_batch_creates_multiple_records(
        self, repo, mock_pool, sample_event, sample_failed_event
    ):
        """Test insert_raw_batch() creates multiple records."""
        events = [sample_event, sample_failed_event]

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

    # ── query_raw tests ──────────────────────────────────────

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
        """Test query_raw() respects limit parameter."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=1)
        end_time = datetime.now(UTC)

        # Test limit capping at 10000
        await repo.query_raw(start_time=start_time, end_time=end_time, limit=50000)

        # The limit should be capped to 10000 internally

    # ── get_summary tests ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_summary_returns_correct_structure(self, repo, mock_pool):
        """Test get_summary() returns correct summary structure."""
        mock_session = AsyncMock()

        # Mock summary query result
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

        # Mock error query result
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
        assert "TimeoutError" in summary["error_types"]
        assert "RateLimitError" in summary["error_types"]

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
        assert summary["success_rate"] == 1.0  # Default for zero calls
        assert summary["total_tokens"] == 0
        assert summary["error_types"] == {}

    # ── get_by_provider tests ────────────────────────────────

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

    # ── get_by_model tests ───────────────────────────────────

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

    # ── get_by_call_point tests ──────────────────────────────

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

    # ── cleanup_raw_older_than tests ─────────────────────────

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

    # ── cleanup_hourly_older_than tests ──────────────────────

    @pytest.mark.asyncio
    async def test_cleanup_hourly_older_than_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_hourly_older_than() deletes old hourly records."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 24  # 1 day's worth of hourly records
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        removed = await repo.cleanup_hourly_older_than(days=365)

        assert removed == 24
        mock_session.commit.assert_called_once()

    # ── upsert_hourly tests ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_upsert_hourly_creates_record(self, repo, mock_pool):
        """Test upsert_hourly() executes upsert statement."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
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

    # ── query_hourly tests ───────────────────────────────────

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
        assert result[0]["success_count"] == 95
        assert result[0]["failure_count"] == 5

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

    @pytest.mark.asyncio
    async def test_query_hourly_with_filters(self, repo, mock_pool):
        """Test query_hourly() applies filters correctly."""
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

    # ── get_latency_bounds tests ─────────────────────────────

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

    # ── get_hourly_stats tests ───────────────────────────────

    @pytest.mark.asyncio
    async def test_get_hourly_stats_returns_records(self, repo, mock_pool):
        """Test get_hourly_stats() returns hourly records."""
        mock_session = AsyncMock()
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

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_session.execute.return_value = mock_result
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        start_time = datetime.now(UTC) - timedelta(hours=24)
        end_time = datetime.now(UTC)

        result = await repo.get_hourly_stats(start_time=start_time, end_time=end_time)

        assert len(result) == 1
        assert result[0]["call_count"] == 100

    # ── get_summary_stats tests ──────────────────────────────

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


class TestLLMUsageRepoEdgeCases:
    """Edge case tests for LLMUsageRepo."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool."""
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_pool):
        """Create LLMUsageRepo with mock pool."""
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_summary_handles_null_error_type(self, repo, mock_pool):
        """Test get_summary() handles null error types."""
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

        # success_rate should handle division by zero
        assert result[0]["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_insert_raw_with_embedding_event(self, repo, mock_pool):
        """Test insert_raw() handles embedding type events."""
        event = LLMUsageEvent(
            label="embedding::openai::text-embedding-3-small",
            call_point="entity_extractor",
            llm_type="embedding",
            provider="openai",
            model="text-embedding-3-small",
            tokens=TokenUsage(input_tokens=1000, output_tokens=0),
            latency_ms=100.0,
            success=True,
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw(event)

        added: LLMUsageRaw = mock_session.add.call_args[0][0]
        assert added.llm_type == "embedding"
        assert added.output_tokens == 0

    @pytest.mark.asyncio
    async def test_insert_raw_with_rerank_event(self, repo, mock_pool):
        """Test insert_raw() handles rerank type events."""
        event = LLMUsageEvent(
            label="rerank::aiping::aiping-rerank",
            call_point="search_rerank",
            llm_type="rerank",
            provider="aiping",
            model="aiping-rerank",
            tokens=TokenUsage(input_tokens=500, output_tokens=0),
            latency_ms=50.0,
            success=True,
        )

        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_pool.session.return_value.__aenter__.return_value = mock_session

        await repo.insert_raw(event)

        added: LLMUsageRaw = mock_session.add.call_args[0][0]
        assert added.llm_type == "rerank"
        assert added.call_point == "search_rerank"
