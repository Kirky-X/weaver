# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMUsageAggregatorThread and LLMUsageRawCleanupThread."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLLMUsageAggregatorThread:
    """Tests for LLMUsageAggregatorThread."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.scan = AsyncMock()
        redis.delete = AsyncMock()
        redis.client = MagicMock()
        redis.client.hgetall = AsyncMock()
        return redis

    @pytest.fixture
    def mock_postgres(self):
        """Create mock PostgreSQL pool."""
        return MagicMock()

    @pytest.fixture
    def aggregator(self, mock_redis, mock_postgres):
        """Create aggregator instance."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        return LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
            interval_minutes=5,
        )

    def test_init_sets_parameters(self, mock_redis, mock_postgres):
        """Test aggregator initializes with correct parameters."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
            interval_minutes=10,
        )

        assert aggregator._redis is mock_redis
        assert aggregator._postgres is mock_postgres
        assert aggregator._interval == 600  # 10 minutes in seconds

    def test_start_creates_thread(self, aggregator):
        """Test start() creates daemon thread."""
        aggregator.start()

        assert aggregator._thread is not None
        assert aggregator._thread.daemon is True
        assert aggregator._thread.name == "llm-usage-aggregator"

        aggregator.stop()

    def test_stop_sets_event(self, aggregator):
        """Test stop() sets stop event."""
        aggregator.stop()

        assert aggregator._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_aggregate_data_basic(self, aggregator):
        """Test _aggregate_data groups by label and call_point."""
        data = {
            "chat::openai::gpt-4::classifier::count": "10",
            "chat::openai::gpt-4::classifier::input_tok": "1000",
            "chat::openai::gpt-4::classifier::output_tok": "500",
            "chat::openai::gpt-4::classifier::total_tok": "1500",
            "chat::openai::gpt-4::classifier::latency_ms": "5000",
            "chat::openai::gpt-4::classifier::success": "9",
            "chat::openai::gpt-4::classifier::failure": "1",
        }

        result = aggregator._aggregate_data(data)

        assert ("chat::openai::gpt-4", "classifier") in result
        agg = result[("chat::openai::gpt-4", "classifier")]
        assert agg["count"] == 10
        assert agg["input_tok"] == 1000
        assert agg["output_tok"] == 500
        assert agg["total_tok"] == 1500
        assert agg["latency_ms"] == 5000.0
        assert agg["success"] == 9
        assert agg["failure"] == 1
        assert agg["llm_type"] == "chat"
        assert agg["provider"] == "openai"
        assert agg["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_aggregate_data_multiple_groups(self, aggregator):
        """Test _aggregate_data handles multiple groups."""
        data = {
            "chat::openai::gpt-4::classifier::count": "10",
            "chat::anthropic::claude-3::analyzer::count": "5",
        }

        result = aggregator._aggregate_data(data)

        assert len(result) == 2
        assert ("chat::openai::gpt-4", "classifier") in result
        assert ("chat::anthropic::claude-3", "analyzer") in result

    @pytest.mark.asyncio
    async def test_aggregate_data_invalid_field(self, aggregator):
        """Test _aggregate_data handles invalid fields gracefully."""
        data = {
            "invalid_field_format": "10",
            "chat::openai::gpt-4::classifier::count": "5",
        }

        result = aggregator._aggregate_data(data)

        assert len(result) == 1
        assert ("chat::openai::gpt-4", "classifier") in result

    @pytest.mark.asyncio
    async def test_aggregate_data_two_part_label(self, aggregator):
        """Test _aggregate_data handles two-part labels (provider::model)."""
        data = {
            "openai::gpt-4::classifier::count": "10",
        }

        result = aggregator._aggregate_data(data)

        assert ("openai::gpt-4", "classifier") in result
        agg = result[("openai::gpt-4", "classifier")]
        assert agg["llm_type"] == "chat"  # Default
        assert agg["provider"] == "openai"
        assert agg["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_aggregate_data_single_part_label(self, aggregator):
        """Test _aggregate_data handles single-part labels."""
        data = {
            "gpt-4::classifier::count": "10",
        }

        result = aggregator._aggregate_data(data)

        assert ("gpt-4", "classifier") in result
        agg = result[("gpt-4", "classifier")]
        assert agg["llm_type"] == "chat"
        assert agg["provider"] == "unknown"
        assert agg["model"] == "gpt-4"


class TestLLMUsageRawCleanupThread:
    """Tests for LLMUsageRawCleanupThread."""

    @pytest.fixture
    def mock_postgres(self):
        """Create mock PostgreSQL pool."""
        return MagicMock()

    @pytest.fixture
    def cleanup_thread(self, mock_postgres):
        """Create cleanup thread instance."""
        from modules.analytics.llm_usage.aggregator import LLMUsageRawCleanupThread

        return LLMUsageRawCleanupThread(
            postgres_pool=mock_postgres,
            retention_days=2,
            interval_hours=6,
        )

    def test_init_sets_parameters(self, mock_postgres):
        """Test cleanup thread initializes with correct parameters."""
        from modules.analytics.llm_usage.aggregator import LLMUsageRawCleanupThread

        cleanup = LLMUsageRawCleanupThread(
            postgres_pool=mock_postgres,
            retention_days=7,
            interval_hours=12,
        )

        assert cleanup._postgres is mock_postgres
        assert cleanup._retention_days == 7
        assert cleanup._interval == 12 * 3600  # 12 hours in seconds

    def test_start_creates_thread(self, cleanup_thread):
        """Test start() creates daemon thread."""
        cleanup_thread.start()

        assert cleanup_thread._thread is not None
        assert cleanup_thread._thread.daemon is True
        assert cleanup_thread._thread.name == "llm-usage-raw-cleanup"

        cleanup_thread.stop()

    def test_stop_sets_event(self, cleanup_thread):
        """Test stop() sets stop event."""
        cleanup_thread.stop()

        assert cleanup_thread._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_cleanup_calls_repo(self, mock_postgres):
        """Test _cleanup() calls LLMUsageRepo.cleanup_raw_older_than()."""
        from modules.analytics.llm_usage.aggregator import LLMUsageRawCleanupThread

        cleanup = LLMUsageRawCleanupThread(
            postgres_pool=mock_postgres,
            retention_days=3,
        )

        with patch("modules.analytics.llm_usage.repo.LLMUsageRepo") as MockRepo:
            mock_repo_instance = MagicMock()
            mock_repo_instance.cleanup_raw_older_than = AsyncMock(return_value=100)
            MockRepo.return_value = mock_repo_instance

            await cleanup._cleanup()

            mock_repo_instance.cleanup_raw_older_than.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_flush_no_keys_to_process(self, mock_redis, mock_postgres):
        """Test _flush handles no keys to process."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
        )
        mock_redis.scan = AsyncMock(return_value=(0, []))

        await aggregator._flush()

        # Should complete without errors

    @pytest.mark.asyncio
    async def test_flush_processes_keys(self, mock_redis, mock_postgres):
        """Test _flush processes keys correctly."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
        )

        # Mock Redis scan to return a key
        mock_redis.scan = AsyncMock(
            side_effect=[
                (0, ["llm:usage:2024011510"]),  # First scan returns key
            ]
        )
        mock_redis.delete = AsyncMock()

        # Mock hgetall to return empty (key will be deleted)
        mock_redis.client.hgetall = AsyncMock(return_value={})

        await aggregator._flush()

        # Key should be deleted
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_flush_with_data(self, mock_redis, mock_postgres):
        """Test _flush processes keys with data."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
        )

        # Mock Redis scan
        mock_redis.scan = AsyncMock(return_value=(0, ["llm:usage:2024011510"]))
        mock_redis.delete = AsyncMock()

        # Mock hgetall to return data
        mock_redis.client.hgetall = AsyncMock(
            return_value={
                "chat::openai::gpt-4::classifier::count": "10",
                "chat::openai::gpt-4::classifier::input_tok": "1000",
                "chat::openai::gpt-4::classifier::output_tok": "500",
                "chat::openai::gpt-4::classifier::total_tok": "1500",
                "chat::openai::gpt-4::classifier::latency_ms": "5000",
                "chat::openai::gpt-4::classifier::success": "10",
                "chat::openai::gpt-4::classifier::failure": "0",
            }
        )

        with patch("modules.analytics.llm_usage.repo.LLMUsageRepo") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_latency_bounds = AsyncMock(return_value=(100.0, 1000.0))
            mock_repo.upsert_hourly = AsyncMock()
            MockRepo.return_value = mock_repo

            await aggregator._flush()

            # Verify upsert was called
            mock_repo.upsert_hourly.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_handles_error_for_key(self, mock_redis, mock_postgres):
        """Test _flush handles errors for individual keys."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
        )

        # Mock Redis scan to return multiple keys
        mock_redis.scan = AsyncMock(
            side_effect=[
                (0, ["llm:usage:2024011510", "llm:usage:2024011511"]),
            ]
        )
        mock_redis.delete = AsyncMock()

        # First call raises error, second succeeds
        call_count = [0]

        async def mock_hgetall(key):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Redis error")
            return {}

        mock_redis.client.hgetall = mock_hgetall

        await aggregator._flush()

        # Should handle error gracefully


class TestLLMUsageAggregatorThreadEdgeCases:
    """Edge case tests for LLMUsageAggregatorThread."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.scan = AsyncMock()
        redis.delete = AsyncMock()
        redis.client = MagicMock()
        redis.client.hgetall = AsyncMock()
        return redis

    @pytest.fixture
    def mock_postgres(self):
        """Create mock PostgreSQL pool."""
        return MagicMock()

    @pytest.fixture
    def aggregator(self, mock_redis, mock_postgres):
        """Create aggregator instance."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        return LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
            interval_minutes=5,
        )

    @pytest.mark.asyncio
    async def test_flush_current_hour_excluded(self, mock_redis, mock_postgres):
        """Test _flush excludes current hour bucket."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
        )

        # Get current hour key
        now = datetime.now(UTC)
        current_hour_key = f"llm:usage:{now.strftime('%Y%m%d%H')}"

        mock_redis.scan = AsyncMock(return_value=(0, [current_hour_key]))

        await aggregator._flush()

        # Current hour should be excluded, delete not called
        mock_redis.delete.assert_not_called()

    def test_thread_name(self, aggregator):
        """Test thread has correct name."""
        aggregator.start()

        assert aggregator._thread.name == "llm-usage-aggregator"

        aggregator.stop()

    def test_thread_is_daemon(self, aggregator):
        """Test thread is daemon thread."""
        aggregator.start()

        assert aggregator._thread.daemon is True

        aggregator.stop()

    @pytest.mark.asyncio
    async def test_execute_flush_handles_runtime_error(self, mock_redis, mock_postgres):
        """Test _execute_flush handles RuntimeError gracefully."""
        from modules.analytics.llm_usage.aggregator import LLMUsageAggregatorThread

        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
        )

        # Create a closed loop
        import asyncio

        loop = asyncio.new_event_loop()
        loop.close()

        # Should not raise
        aggregator._execute_flush(loop)

    @pytest.mark.asyncio
    async def test_cleanup_thread_execute_handles_runtime_error(self, mock_postgres):
        """Test cleanup _execute_cleanup handles RuntimeError."""
        from modules.analytics.llm_usage.aggregator import LLMUsageRawCleanupThread

        cleanup = LLMUsageRawCleanupThread(
            postgres_pool=mock_postgres,
        )

        import asyncio

        loop = asyncio.new_event_loop()
        loop.close()

        # Should not raise
        cleanup._execute_cleanup(loop)
