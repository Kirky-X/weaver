# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for EvalCompareRepo - Repository for LLM comparison statistics."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event import LLMCompareEvent
from modules.analytics.llm_compare.repo import EvalCompareRepo
from tests.helpers import create_mock_relational_pool


class TestEvalCompareRepoInit:
    """Test EvalCompareRepo initialization."""

    def test_basic_initialization(self):
        """Test basic initialization with relational pool."""
        pool = MagicMock()
        repo = EvalCompareRepo(pool=pool)

        assert repo._pool == pool


class TestEvalCompareRepoInsertRaw:
    """Test insert_raw method."""

    # Uses conftest.py fixtures: mock_relational_pool, repo, sample_event

    @pytest.fixture
    def sample_event(self):
        """Create sample LLMCompareEvent."""
        return LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 30, 0, tzinfo=UTC),
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            primary_latency=150.5,
            candidate_latency=200.3,
            primary_success=True,
            candidate_success=False,
        )

    @pytest.mark.asyncio
    async def test_insert_raw_creates_record(
        self,
        repo,
        mock_relational_pool,
        sample_event,
    ):
        """Test insert_raw creates LLMCompareHourly record."""
        await repo.insert_raw(sample_event)

        # Should call session.add
        mock_relational_pool.session.return_value.add.assert_called_once()

        # Should commit
        mock_relational_pool.session.return_value.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_raw_truncates_time_to_hour(
        self,
        repo,
        mock_relational_pool,
        sample_event,
    ):
        """Test insert_raw truncates timestamp to hour bucket."""
        await repo.insert_raw(sample_event)

        # Get the added record
        added_record = mock_relational_pool.session.return_value.add.call_args[0][0]

        # Time should be truncated to hour
        expected_time = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)
        assert added_record.time_bucket == expected_time

    @pytest.mark.asyncio
    async def test_insert_raw_populates_all_fields(
        self,
        repo,
        mock_relational_pool,
        sample_event,
    ):
        """Test insert_raw populates all record fields."""
        await repo.insert_raw(sample_event)

        added_record = mock_relational_pool.session.return_value.add.call_args[0][0]

        assert added_record.call_point == "classifier"
        assert added_record.primary_model == "gpt-4"
        assert added_record.candidate_model == "claude-3"
        assert added_record.comparison_count == 1
        assert added_record.primary_latency_sum == 150.5
        assert added_record.candidate_latency_sum == 200.3
        assert added_record.primary_success_count == 1
        assert added_record.candidate_success_count == 0

    @pytest.mark.asyncio
    async def test_insert_raw_success_false(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test insert_raw with failed models."""
        event = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            call_point="test",
            primary_model="model-a",
            candidate_model="model-b",
            primary_latency=100.0,
            candidate_latency=120.0,
            primary_success=False,
            candidate_success=False,
        )

        await repo.insert_raw(event)

        added_record = mock_relational_pool.session.return_value.add.call_args[0][0]

        assert added_record.primary_success_count == 0
        assert added_record.candidate_success_count == 0


class TestEvalCompareRepoUpsertHourly:
    """Test upsert_hourly method."""

    # Uses conftest.py fixtures: mock_relational_pool, repo

    @pytest.mark.asyncio
    async def test_upsert_hourly_executes_insert(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test upsert_hourly executes insert statement."""
        time_bucket = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)

        await repo.upsert_hourly(
            time_bucket=time_bucket,
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            comparison_count=10,
            primary_latency_sum=1500.0,
            candidate_latency_sum=2000.0,
            primary_success_count=8,
            candidate_success_count=7,
        )

        # Should execute statement
        mock_relational_pool.session.return_value.execute.assert_called_once()

        # Should commit
        mock_relational_pool.session.return_value.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_hourly_with_zero_counts(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test upsert_hourly with zero counts."""
        time_bucket = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)

        await repo.upsert_hourly(
            time_bucket=time_bucket,
            call_point="test",
            primary_model="model-a",
            candidate_model="model-b",
            comparison_count=0,
            primary_latency_sum=0.0,
            candidate_latency_sum=0.0,
            primary_success_count=0,
            candidate_success_count=0,
        )

        # Should still execute and commit
        mock_relational_pool.session.return_value.execute.assert_called_once()
        mock_relational_pool.session.return_value.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_hourly_large_values(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test upsert_hourly with large values."""
        time_bucket = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)

        await repo.upsert_hourly(
            time_bucket=time_bucket,
            call_point="test",
            primary_model="model-a",
            candidate_model="model-b",
            comparison_count=1000000,
            primary_latency_sum=150000000.0,
            candidate_latency_sum=200000000.0,
            primary_success_count=950000,
            candidate_success_count=900000,
        )

        mock_relational_pool.session.return_value.execute.assert_called_once()


class TestEvalCompareRepoGetComparisonStats:
    """Test get_comparison_stats method."""

    # Uses conftest.py fixtures: mock_relational_pool, repo

    @pytest.mark.asyncio
    async def test_get_comparison_stats_returns_list(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test get_comparison_stats returns list."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        start_time = datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)

        result = await repo.get_comparison_stats(
            call_point="classifier",
            start_time=start_time,
            end_time=end_time,
        )

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_comparison_stats_with_data(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test get_comparison_stats returns proper data structure."""
        # Mock row data
        mock_row = MagicMock()
        mock_row.primary_model = "gpt-4"
        mock_row.candidate_model = "claude-3"
        mock_row.total_comparisons = 100
        mock_row.avg_primary_latency = 150.5
        mock_row.avg_candidate_latency = 200.3
        mock_row.primary_success_count = 95
        mock_row.candidate_success_count = 90

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        start_time = datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)

        result = await repo.get_comparison_stats(
            call_point="classifier",
            start_time=start_time,
            end_time=end_time,
        )

        assert len(result) == 1
        stat = result[0]

        assert stat["primary_model"] == "gpt-4"
        assert stat["candidate_model"] == "claude-3"
        assert stat["total_comparisons"] == 100
        assert stat["avg_primary_latency"] == 150.5
        assert stat["avg_candidate_latency"] == 200.3
        assert isinstance(stat["primary_success_rate"], float)
        assert isinstance(stat["candidate_success_rate"], float)

    @pytest.mark.asyncio
    async def test_get_comparison_stats_success_rate_calculation(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test success rate calculation."""
        mock_row = MagicMock()
        mock_row.primary_model = "model-a"
        mock_row.candidate_model = "model-b"
        mock_row.total_comparisons = 100
        mock_row.avg_primary_latency = 100.0
        mock_row.avg_candidate_latency = 120.0
        mock_row.primary_success_count = 85
        mock_row.candidate_success_count = 75

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        start_time = datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)

        result = await repo.get_comparison_stats(
            call_point="test",
            start_time=start_time,
            end_time=end_time,
        )

        stat = result[0]
        assert stat["primary_success_rate"] == pytest.approx(0.85)
        assert stat["candidate_success_rate"] == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_get_comparison_stats_empty_result(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test get_comparison_stats with no data."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        start_time = datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)

        result = await repo.get_comparison_stats(
            call_point="empty",
            start_time=start_time,
            end_time=end_time,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_comparison_stats_null_handling(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test get_comparison_stats handles null values."""
        mock_row = MagicMock()
        mock_row.primary_model = "model-a"
        mock_row.candidate_model = "model-b"
        mock_row.total_comparisons = None
        mock_row.avg_primary_latency = None
        mock_row.avg_candidate_latency = None
        mock_row.primary_success_count = None
        mock_row.candidate_success_count = None

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        start_time = datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)

        result = await repo.get_comparison_stats(
            call_point="test",
            start_time=start_time,
            end_time=end_time,
        )

        stat = result[0]
        assert stat["total_comparisons"] == 0
        assert stat["avg_primary_latency"] == 0.0
        assert stat["avg_candidate_latency"] == 0.0

    @pytest.mark.asyncio
    async def test_get_comparison_stats_multiple_rows(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test get_comparison_stats with multiple result rows."""
        mock_row1 = MagicMock()
        mock_row1.primary_model = "gpt-4"
        mock_row1.candidate_model = "claude-3"
        mock_row1.total_comparisons = 100
        mock_row1.avg_primary_latency = 150.0
        mock_row1.avg_candidate_latency = 200.0
        mock_row1.primary_success_count = 95
        mock_row1.candidate_success_count = 90

        mock_row2 = MagicMock()
        mock_row2.primary_model = "gpt-4"
        mock_row2.candidate_model = "llama-3"
        mock_row2.total_comparisons = 50
        mock_row2.avg_primary_latency = 150.0
        mock_row2.avg_candidate_latency = 180.0
        mock_row2.primary_success_count = 48
        mock_row2.candidate_success_count = 45

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row1, mock_row2]
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        start_time = datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC)
        end_time = datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)

        result = await repo.get_comparison_stats(
            call_point="classifier",
            start_time=start_time,
            end_time=end_time,
        )

        assert len(result) == 2
        assert result[0]["candidate_model"] == "claude-3"
        assert result[1]["candidate_model"] == "llama-3"


class TestEvalCompareRepoCleanupOlderThan:
    """Test cleanup_older_than method."""

    # Uses conftest.py fixtures: mock_relational_pool, repo

    @pytest.mark.asyncio
    async def test_cleanup_older_than_deletes_records(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test cleanup_older_than deletes old records."""
        mock_result = MagicMock()
        mock_result.rowcount = 50
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        removed = await repo.cleanup_older_than(days=7)

        # Should execute delete
        mock_relational_pool.session.return_value.execute.assert_called_once()
        mock_relational_pool.session.return_value.commit.assert_called_once()
        assert removed == 50

    @pytest.mark.asyncio
    async def test_cleanup_older_than_default_days(self, repo, mock_relational_pool):
        """Test cleanup_older_than uses default 7 days."""
        mock_result = MagicMock()
        mock_result.rowcount = 10
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        await repo.cleanup_older_than()

        # Should use default 7 days
        mock_relational_pool.session.return_value.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_older_than_custom_days(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test cleanup_older_than with custom days parameter."""
        mock_result = MagicMock()
        mock_result.rowcount = 100
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        removed = await repo.cleanup_older_than(days=30)

        assert removed == 100

    @pytest.mark.asyncio
    async def test_cleanup_older_than_zero_days(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test cleanup_older_than with zero days (delete everything)."""
        mock_result = MagicMock()
        mock_result.rowcount = 1000
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        removed = await repo.cleanup_older_than(days=0)

        assert removed == 1000

    @pytest.mark.asyncio
    async def test_cleanup_older_than_no_records(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test cleanup_older_than when no records to delete."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        removed = await repo.cleanup_older_than(days=7)

        assert removed == 0

    @pytest.mark.asyncio
    async def test_cleanup_older_than_logs_result(
        self,
        repo,
        mock_relational_pool,
    ):
        """Test cleanup_older_than logs the cleanup result."""
        mock_result = MagicMock()
        mock_result.rowcount = 25
        mock_relational_pool.session.return_value.execute.return_value = mock_result

        with patch("modules.analytics.llm_compare.repo.log") as mock_log:
            await repo.cleanup_older_than(days=14)

            # Should log completion
            mock_log.info.assert_called_once()
            call_kwargs = mock_log.info.call_args[1]
            assert call_kwargs["days"] == 14
            assert call_kwargs["removed"] == 25


class TestEvalCompareRepoIntegration:
    """Integration tests for EvalCompareRepo."""

    @pytest.mark.asyncio
    async def test_full_workflow_insert_and_query(self):
        """Test complete workflow: insert -> upsert -> query -> cleanup."""
        pool = create_mock_relational_pool()
        session = pool.session.return_value

        repo = EvalCompareRepo(pool=pool)

        # Insert raw event
        event = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 30, 0, tzinfo=UTC),
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            primary_latency=150.0,
            candidate_latency=200.0,
            primary_success=True,
            candidate_success=True,
        )

        await repo.insert_raw(event)
        assert session.add.called

        # Upsert hourly
        await repo.upsert_hourly(
            time_bucket=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            comparison_count=10,
            primary_latency_sum=1500.0,
            candidate_latency_sum=2000.0,
            primary_success_count=9,
            candidate_success_count=8,
        )
        assert session.execute.called

        # Query stats
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.primary_model = "gpt-4"
        mock_row.candidate_model = "claude-3"
        mock_row.total_comparisons = 10
        mock_row.avg_primary_latency = 150.0
        mock_row.avg_candidate_latency = 200.0
        mock_row.primary_success_count = 9
        mock_row.candidate_success_count = 8
        mock_result.all.return_value = [mock_row]
        session.execute.return_value = mock_result

        stats = await repo.get_comparison_stats(
            call_point="classifier",
            start_time=datetime(2026, 4, 14, 0, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC),
        )

        assert len(stats) == 1
        assert stats[0]["total_comparisons"] == 10

        # Cleanup
        mock_cleanup_result = MagicMock()
        mock_cleanup_result.rowcount = 5
        session.execute.return_value = mock_cleanup_result

        removed = await repo.cleanup_older_than(days=7)
        assert removed == 5
