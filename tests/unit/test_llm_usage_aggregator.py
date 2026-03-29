# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLM usage aggregator and cleanup threads."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event.bus import LLMUsageEvent
from core.llm.request import TokenUsage
from modules.scheduler.llm_usage_aggregator import (
    LLMUsageAggregatorThread,
    LLMUsageRawCleanupThread,
)
from modules.storage.llm_usage_repo import LLMUsageRepo


# ── LLMUsageRepo Tests ────────────────────────────────────────


class TestLLMUsageRepo:
    """Tests for LLMUsageRepo."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock PostgreSQL pool."""
        pool = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        pool.session.return_value = session
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> LLMUsageRepo:
        """Create a LLMUsageRepo instance with mock pool."""
        return LLMUsageRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_insert_raw(self, repo: LLMUsageRepo, mock_pool: MagicMock) -> None:
        """Test inserting a single raw record."""
        event = LLMUsageEvent(
            label="chat::aiping::qwen-plus",
            call_point="classifier",
            llm_type="chat",
            provider="aiping",
            model="qwen-plus",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=250.5,
            success=True,
        )

        await repo.insert_raw(event)

        # Verify session.add was called
        session = mock_pool.session.return_value
        assert session.add.called
        assert session.commit.called

    @pytest.mark.asyncio
    async def test_insert_raw_batch(self, repo: LLMUsageRepo, mock_pool: MagicMock) -> None:
        """Test inserting a batch of raw records."""
        events = [
            LLMUsageEvent(
                label="chat::aiping::qwen-plus",
                call_point="classifier",
                llm_type="chat",
                provider="aiping",
                model="qwen-plus",
                tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
                latency_ms=250.5,
                success=True,
            ),
            LLMUsageEvent(
                label="embedding::aiping::text-embedding-3-large",
                call_point="entity_extractor",
                llm_type="embedding",
                provider="aiping",
                model="text-embedding-3-large",
                tokens=TokenUsage(input_tokens=200, output_tokens=0, total_tokens=200),
                latency_ms=150.0,
                success=True,
            ),
        ]

        count = await repo.insert_raw_batch(events)

        assert count == 2
        session = mock_pool.session.return_value
        assert session.add_all.called
        assert session.commit.called

    @pytest.mark.asyncio
    async def test_insert_raw_batch_empty(self, repo: LLMUsageRepo) -> None:
        """Test inserting an empty batch."""
        count = await repo.insert_raw_batch([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_latency_bounds(self, repo: LLMUsageRepo, mock_pool: MagicMock) -> None:
        """Test querying latency bounds."""
        time_bucket = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        # Mock the result
        mock_result = MagicMock()
        mock_result.first.return_value = MagicMock(min_latency=100.0, max_latency=500.0)

        session = mock_pool.session.return_value
        session.execute.return_value = mock_result

        min_lat, max_lat = await repo.get_latency_bounds(
            time_bucket, "chat::aiping::qwen-plus", "classifier"
        )

        assert min_lat == 100.0
        assert max_lat == 500.0

    @pytest.mark.asyncio
    async def test_get_latency_bounds_no_records(
        self, repo: LLMUsageRepo, mock_pool: MagicMock
    ) -> None:
        """Test querying latency bounds when no records exist."""
        time_bucket = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        # Mock the result with None
        mock_result = MagicMock()
        mock_result.first.return_value = None

        session = mock_pool.session.return_value
        session.execute.return_value = mock_result

        min_lat, max_lat = await repo.get_latency_bounds(
            time_bucket, "chat::aiping::qwen-plus", "classifier"
        )

        assert min_lat == 0.0
        assert max_lat == 0.0

    @pytest.mark.asyncio
    async def test_cleanup_raw_older_than(self, repo: LLMUsageRepo, mock_pool: MagicMock) -> None:
        """Test cleaning up old raw records."""
        # Mock the result
        mock_result = MagicMock()
        mock_result.rowcount = 42

        session = mock_pool.session.return_value
        session.execute.return_value = mock_result

        deleted = await repo.cleanup_raw_older_than(2)

        assert deleted == 42
        assert session.commit.called


# ── LLMUsageAggregatorThread Tests ───────────────────────────────────


class TestLLMUsageAggregatorThread:
    """Tests for LLMUsageAggregatorThread."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        redis = MagicMock()
        redis.client = AsyncMock()
        return redis

    @pytest.fixture
    def mock_postgres(self) -> MagicMock:
        """Create a mock PostgreSQL pool."""
        pool = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        pool.session.return_value = session
        return pool

    @pytest.fixture
    def aggregator(
        self, mock_redis: MagicMock, mock_postgres: MagicMock
    ) -> LLMUsageAggregatorThread:
        """Create an aggregator thread instance."""
        return LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
            interval_minutes=5,
        )

    def test_aggregate_data(self, aggregator: LLMUsageAggregatorThread) -> None:
        """Test aggregating Redis hash data."""
        # Simulate Redis HGETALL result
        data = {
            "chat::aiping::qwen-plus::classifier::count": "10",
            "chat::aiping::qwen-plus::classifier::input_tok": "1000",
            "chat::aiping::qwen-plus::classifier::output_tok": "500",
            "chat::aiping::qwen-plus::classifier::total_tok": "1500",
            "chat::aiping::qwen-plus::classifier::latency_ms": "2500",
            "chat::aiping::qwen-plus::classifier::success": "9",
            "chat::aiping::qwen-plus::classifier::failure": "1",
        }

        result = aggregator._aggregate_data(data)

        assert ("chat::aiping::qwen-plus", "classifier") in result
        agg = result[("chat::aiping::qwen-plus", "classifier")]
        assert agg["count"] == 10
        assert agg["input_tok"] == 1000
        assert agg["output_tok"] == 500
        assert agg["total_tok"] == 1500
        assert agg["latency_ms"] == 2500.0
        assert agg["success"] == 9
        assert agg["failure"] == 1
        assert agg["llm_type"] == "chat"
        assert agg["provider"] == "aiping"
        assert agg["model"] == "qwen-plus"

    def test_aggregate_data_multiple_groups(
        self, aggregator: LLMUsageAggregatorThread
    ) -> None:
        """Test aggregating data with multiple groups."""
        data = {
            "chat::aiping::qwen-plus::classifier::count": "10",
            "chat::aiping::qwen-plus::classifier::input_tok": "1000",
            "chat::aiping::qwen-plus::classifier::output_tok": "500",
            "chat::aiping::qwen-plus::classifier::total_tok": "1500",
            "chat::aiping::qwen-plus::classifier::latency_ms": "2500",
            "chat::aiping::qwen-plus::classifier::success": "10",
            "chat::aiping::qwen-plus::classifier::failure": "0",
            "embedding::aiping::text-embedding::entity_extractor::count": "5",
            "embedding::aiping::text-embedding::entity_extractor::input_tok": "2000",
            "embedding::aiping::text-embedding::entity_extractor::output_tok": "0",
            "embedding::aiping::text-embedding::entity_extractor::total_tok": "2000",
            "embedding::aiping::text-embedding::entity_extractor::latency_ms": "750",
            "embedding::aiping::text-embedding::entity_extractor::success": "5",
            "embedding::aiping::text-embedding::entity_extractor::failure": "0",
        }

        result = aggregator._aggregate_data(data)

        assert len(result) == 2
        assert ("chat::aiping::qwen-plus", "classifier") in result
        assert ("embedding::aiping::text-embedding", "entity_extractor") in result

    def test_aggregate_data_invalid_field(
        self, aggregator: LLMUsageAggregatorThread
    ) -> None:
        """Test aggregating data with invalid field format."""
        data = {
            "invalid_field": "100",
            "chat::aiping::qwen-plus::classifier::count": "10",
        }

        result = aggregator._aggregate_data(data)

        # Should only have the valid field
        assert len(result) == 1
        assert ("chat::aiping::qwen-plus", "classifier") in result

    def test_start_and_stop(
        self, aggregator: LLMUsageAggregatorThread, mock_redis: MagicMock
    ) -> None:
        """Test starting and stopping the aggregator thread."""
        # Mock scan to return no keys
        mock_redis.scan = AsyncMock(return_value=(0, []))

        aggregator.start()
        assert aggregator._thread is not None
        assert aggregator._thread.is_alive()

        aggregator.stop()

        # Wait for thread to stop
        aggregator._thread.join(timeout=2)
        assert not aggregator._thread.is_alive()

    @pytest.mark.asyncio
    async def test_flush_no_keys(
        self, aggregator: LLMUsageAggregatorThread, mock_redis: MagicMock
    ) -> None:
        """Test flush with no keys to process."""
        mock_redis.scan = AsyncMock(return_value=(0, []))

        await aggregator._flush()

        # Should complete without errors
        mock_redis.scan.assert_called()

    @pytest.mark.asyncio
    async def test_flush_excludes_current_hour(
        self, aggregator: LLMUsageAggregatorThread, mock_redis: MagicMock
    ) -> None:
        """Test that current hour bucket is excluded from processing."""
        now = datetime.now(UTC)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        current_hour_key = f"llm:usage:{current_hour.strftime('%Y%m%d%H')}"
        past_hour_key = f"llm:usage:{(current_hour - timedelta(hours=1)).strftime('%Y%m%d%H')}"

        # Mock scan to return current and past hour keys
        mock_redis.scan = AsyncMock(
            side_effect=[
                (1, [current_hour_key, past_hour_key]),
                (0, []),
            ]
        )
        mock_redis.client.hgetall = AsyncMock(return_value={})
        mock_redis.delete = AsyncMock()

        await aggregator._flush()

        # Should only process past hour key, not current hour
        mock_redis.delete.assert_called_once_with(past_hour_key)


# ── LLMUsageRawCleanupThread Tests ─────────────────────────────────────


class TestLLMUsageRawCleanupThread:
    """Tests for LLMUsageRawCleanupThread."""

    @pytest.fixture
    def mock_postgres(self) -> MagicMock:
        """Create a mock PostgreSQL pool."""
        pool = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        pool.session.return_value = session
        return pool

    @pytest.fixture
    def cleanup_thread(self, mock_postgres: MagicMock) -> LLMUsageRawCleanupThread:
        """Create a cleanup thread instance."""
        return LLMUsageRawCleanupThread(
            postgres_pool=mock_postgres,
            retention_days=2,
            interval_hours=6,
        )

    def test_start_and_stop(
        self, cleanup_thread: LLMUsageRawCleanupThread, mock_postgres: MagicMock
    ) -> None:
        """Test starting and stopping the cleanup thread."""
        # Mock the session to return empty result
        session = mock_postgres.session.return_value
        mock_result = MagicMock()
        mock_result.rowcount = 0
        session.execute.return_value = mock_result

        cleanup_thread.start()
        assert cleanup_thread._thread is not None
        assert cleanup_thread._thread.is_alive()

        cleanup_thread.stop()

        # Wait for thread to stop
        cleanup_thread._thread.join(timeout=2)
        assert not cleanup_thread._thread.is_alive()

    @pytest.mark.asyncio
    async def test_cleanup(
        self, cleanup_thread: LLMUsageRawCleanupThread, mock_postgres: MagicMock
    ) -> None:
        """Test cleanup execution."""
        # Mock the session
        session = mock_postgres.session.return_value
        mock_result = MagicMock()
        mock_result.rowcount = 100
        session.execute.return_value = mock_result

        await cleanup_thread._cleanup()

        # Should have executed delete
        assert session.execute.called
        assert session.commit.called


# ── Integration-style Tests ───────────────────────────────────────────


class TestAggregatorIntegration:
    """Integration-style tests for aggregator thread."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        redis = MagicMock()
        redis.client = AsyncMock()
        return redis

    @pytest.fixture
    def mock_postgres(self) -> MagicMock:
        """Create a mock PostgreSQL pool."""
        pool = MagicMock()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        pool.session.return_value = session
        return pool

    @pytest.mark.asyncio
    async def test_full_flush_flow(
        self, mock_redis: MagicMock, mock_postgres: MagicMock
    ) -> None:
        """Test the complete flush flow with mocked dependencies."""
        aggregator = LLMUsageAggregatorThread(
            redis_client=mock_redis,
            postgres_pool=mock_postgres,
        )

        # Create a past hour bucket key
        now = datetime.now(UTC)
        past_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        past_hour_key = f"llm:usage:{past_hour.strftime('%Y%m%d%H')}"

        # Mock Redis operations
        mock_redis.scan = AsyncMock(
            side_effect=[
                (0, [past_hour_key]),
            ]
        )
        mock_redis.client.hgetall = AsyncMock(
            return_value={
                "chat::aiping::qwen-plus::classifier::count": "10",
                "chat::aiping::qwen-plus::classifier::input_tok": "1000",
                "chat::aiping::qwen-plus::classifier::output_tok": "500",
                "chat::aiping::qwen-plus::classifier::total_tok": "1500",
                "chat::aiping::qwen-plus::classifier::latency_ms": "2500",
                "chat::aiping::qwen-plus::classifier::success": "10",
                "chat::aiping::qwen-plus::classifier::failure": "0",
            }
        )
        mock_redis.delete = AsyncMock()

        # Mock PostgreSQL operations
        session = mock_postgres.session.return_value
        mock_result = MagicMock()
        mock_result.first.return_value = MagicMock(min_latency=100.0, max_latency=500.0)
        session.execute.return_value = mock_result

        await aggregator._flush()

        # Verify Redis key was deleted
        mock_redis.delete.assert_called_once_with(past_hour_key)

        # Verify PostgreSQL operations were called
        assert session.execute.called
        assert session.commit.called
