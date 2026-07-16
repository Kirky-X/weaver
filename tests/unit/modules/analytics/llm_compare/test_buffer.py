# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for EvalCompareBuffer - Redis buffer for LLM comparison results."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event import LLMCompareEvent
from modules.analytics.llm_compare.buffer import (
    DEFAULT_TTL_SECONDS,
    METRICS,
    REDIS_KEY_PREFIX,
    EvalCompareBuffer,
)


class TestEvalCompareBufferInit:
    """Test EvalCompareBuffer initialization."""

    def test_basic_initialization(self):
        """Test basic initialization with default TTL."""
        cache = MagicMock()
        buffer = EvalCompareBuffer(cache=cache)

        assert buffer._cache == cache
        assert buffer._ttl == DEFAULT_TTL_SECONDS
        assert buffer._ttl == 86400

    def test_custom_ttl_initialization(self):
        """Test initialization with custom TTL."""
        cache = MagicMock()
        custom_ttl = 3600  # 1 hour
        buffer = EvalCompareBuffer(cache=cache, ttl_seconds=custom_ttl)

        assert buffer._cache == cache
        assert buffer._ttl == custom_ttl

    def test_ttl_zero_initialization(self):
        """Test initialization with zero TTL."""
        cache = MagicMock()
        buffer = EvalCompareBuffer(cache=cache, ttl_seconds=0)

        assert buffer._ttl == 0


class TestEvalCompareBufferBucketKey:
    """Test _make_bucket_key method."""

    @pytest.fixture
    def buffer(self):
        """Create buffer instance for testing."""
        cache = MagicMock()
        return EvalCompareBuffer(cache=cache)

    def test_bucket_key_format(self, buffer: EvalCompareBuffer):
        """Test bucket key uses correct format."""
        dt = datetime(2026, 4, 14, 10, 30, 0, tzinfo=UTC)
        key = buffer._make_bucket_key(dt)

        assert key == "llm:compare:2026041410"

    def test_bucket_key_hour_precision(self, buffer: EvalCompareBuffer):
        """Test bucket key has hour precision."""
        dt1 = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)
        dt2 = datetime(2026, 4, 14, 10, 59, 59, tzinfo=UTC)

        key1 = buffer._make_bucket_key(dt1)
        key2 = buffer._make_bucket_key(dt2)

        # Same hour should produce same key
        assert key1 == key2

    def test_bucket_key_different_hours(self, buffer: EvalCompareBuffer):
        """Test different hours produce different keys."""
        dt1 = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)
        dt2 = datetime(2026, 4, 14, 11, 0, 0, tzinfo=UTC)

        key1 = buffer._make_bucket_key(dt1)
        key2 = buffer._make_bucket_key(dt2)

        assert key1 != key2
        assert "2026041410" in key1
        assert "2026041411" in key2

    def test_bucket_key_different_days(self, buffer: EvalCompareBuffer):
        """Test different days produce different keys."""
        dt1 = datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC)
        dt2 = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)

        key1 = buffer._make_bucket_key(dt1)
        key2 = buffer._make_bucket_key(dt2)

        assert key1 != key2


class TestEvalCompareBufferFieldName:
    """Test _make_field_name method."""

    @pytest.fixture
    def buffer(self):
        """Create buffer instance for testing."""
        cache = MagicMock()
        return EvalCompareBuffer(cache=cache)

    def test_field_name_format(self, buffer: EvalCompareBuffer):
        """Test field name uses correct format."""
        field = buffer._make_field_name(
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            metric="count",
        )

        assert field == "classifier::gpt-4::claude-3::count"

    @pytest.mark.parametrize("metric", METRICS)
    def test_all_supported_metrics(self, buffer: EvalCompareBuffer, metric: str):
        """Test field name generation for all supported metrics."""
        field = buffer._make_field_name(
            call_point="test",
            primary_model="model-a",
            candidate_model="model-b",
            metric=metric,
        )

        assert field == f"test::model-a::model-b::{metric}"
        assert metric in field


class TestEvalCompareBufferAccumulate:
    """Test accumulate method - core functionality."""

    @pytest.fixture
    def mock_cache(self):
        """Create mock cache with async methods."""
        cache = MagicMock()
        cache.hincrby = AsyncMock()
        cache.expire = AsyncMock()
        return cache

    @pytest.fixture
    def buffer(self, mock_cache):
        """Create buffer with mock cache."""
        return EvalCompareBuffer(cache=mock_cache, ttl_seconds=3600)

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
    async def test_accumulate_increments_count(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
        sample_event: LLMCompareEvent,
    ):
        """Test that accumulate increments count metric."""
        await buffer.accumulate(sample_event)

        # Should call hincrby for count
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "classifier::gpt-4::claude-3::count",
            1,
        )

    @pytest.mark.asyncio
    async def test_accumulate_increments_latencies(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
        sample_event: LLMCompareEvent,
    ):
        """Test that accumulate increments latency sums."""
        await buffer.accumulate(sample_event)

        # Should increment primary latency (int(150.5) = 150)
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "classifier::gpt-4::claude-3::primary_latency_sum",
            150,
        )

        # Should increment candidate latency (int(200.3) = 200)
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "classifier::gpt-4::claude-3::candidate_latency_sum",
            200,
        )

    @pytest.mark.asyncio
    async def test_accumulate_increments_success_counters(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
        sample_event: LLMCompareEvent,
    ):
        """Test that accumulate increments success counters."""
        await buffer.accumulate(sample_event)

        # Primary success = True, should increment by 1
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "classifier::gpt-4::claude-3::primary_success",
            1,
        )

        # Candidate success = False, should increment by 0
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "classifier::gpt-4::claude-3::candidate_success",
            0,
        )

    @pytest.mark.asyncio
    async def test_accumulate_sets_ttl(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
        sample_event: LLMCompareEvent,
    ):
        """Test that accumulate sets TTL on bucket key."""
        await buffer.accumulate(sample_event)

        mock_cache.expire.assert_called_once_with(
            "llm:compare:2026041410",
            3600,
        )

    @pytest.mark.asyncio
    async def test_accumulate_multiple_events_same_bucket(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
    ):
        """Test accumulating multiple events in same hour bucket."""
        event1 = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 15, 0, tzinfo=UTC),
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            primary_latency=100.0,
            candidate_latency=150.0,
            primary_success=True,
            candidate_success=True,
        )

        event2 = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 45, 0, tzinfo=UTC),
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            primary_latency=200.0,
            candidate_latency=250.0,
            primary_success=False,
            candidate_success=True,
        )

        await buffer.accumulate(event1)
        await buffer.accumulate(event2)

        # hincrby should be called 5 times per event (5 metrics)
        assert mock_cache.hincrby.call_count == 10
        # expire should be called twice (once per accumulate)
        assert mock_cache.expire.call_count == 2

    @pytest.mark.asyncio
    async def test_accumulate_different_call_points(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
    ):
        """Test accumulating events with different call points."""
        event1 = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            call_point="classifier",
            primary_model="gpt-4",
            candidate_model="claude-3",
            primary_latency=100.0,
            candidate_latency=150.0,
            primary_success=True,
            candidate_success=True,
        )

        event2 = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            call_point="embedding",
            primary_model="text-embedding-3",
            candidate_model="embed-v2",
            primary_latency=50.0,
            candidate_latency=60.0,
            primary_success=True,
            candidate_success=True,
        )

        await buffer.accumulate(event1)
        await buffer.accumulate(event2)

        # Should use different field names
        calls = [str(call) for call in mock_cache.hincrby.call_args_list]
        assert any("classifier" in call for call in calls)
        assert any("embedding" in call for call in calls)

    @pytest.mark.asyncio
    async def test_accumulate_handles_exception_gracefully(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
        sample_event: LLMCompareEvent,
    ):
        """Test that accumulate handles exceptions without raising."""
        mock_cache.hincrby.side_effect = Exception("Redis connection failed")

        # Should not raise exception
        await buffer.accumulate(sample_event)

        # Exception should be logged (we can't easily verify logging in unit tests)
        # But the method should complete without raising

    @pytest.mark.asyncio
    async def test_accumulate_both_success_true(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
    ):
        """Test accumulate when both models succeed."""
        event = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            call_point="test",
            primary_model="model-a",
            candidate_model="model-b",
            primary_latency=100.0,
            candidate_latency=120.0,
            primary_success=True,
            candidate_success=True,
        )

        await buffer.accumulate(event)

        # Both success counters should increment by 1
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "test::model-a::model-b::primary_success",
            1,
        )
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "test::model-a::model-b::candidate_success",
            1,
        )

    @pytest.mark.asyncio
    async def test_accumulate_both_success_false(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
    ):
        """Test accumulate when both models fail."""
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

        await buffer.accumulate(event)

        # Both success counters should increment by 0
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "test::model-a::model-b::primary_success",
            0,
        )
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "test::model-a::model-b::candidate_success",
            0,
        )

    @pytest.mark.asyncio
    async def test_accumulate_latency_truncation(
        self,
        buffer: EvalCompareBuffer,
        mock_cache: MagicMock,
    ):
        """Test that latency values are truncated to int."""
        event = LLMCompareEvent(
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=UTC),
            call_point="test",
            primary_model="model-a",
            candidate_model="model-b",
            primary_latency=150.9,  # Should be truncated to 150
            candidate_latency=200.1,  # Should be truncated to 200
            primary_success=True,
            candidate_success=True,
        )

        await buffer.accumulate(event)

        # Verify truncation to int
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "test::model-a::model-b::primary_latency_sum",
            150,
        )
        mock_cache.hincrby.assert_any_call(
            "llm:compare:2026041410",
            "test::model-a::model-b::candidate_latency_sum",
            200,
        )


class TestEvalCompareBufferConstants:
    """Test module constants."""

    def test_redis_key_prefix(self):
        """Test Redis key prefix constant."""
        assert REDIS_KEY_PREFIX == "llm:compare"

    def test_default_ttl_seconds(self):
        """Test default TTL is 24 hours."""
        assert DEFAULT_TTL_SECONDS == 86400

    def test_metrics_tuple(self):
        """Test supported metrics tuple."""
        assert isinstance(METRICS, tuple)
        assert len(METRICS) == 5
        assert "count" in METRICS
        assert "primary_latency_sum" in METRICS
        assert "candidate_latency_sum" in METRICS
        assert "primary_success" in METRICS
        assert "candidate_success" in METRICS
