# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for storage LLMUsageBuffer."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event.bus import LLMUsageEvent
from core.llm.request import TokenUsage
from modules.storage.llm_usage_buffer import (
    DEFAULT_TTL_SECONDS,
    REDIS_KEY_PREFIX,
    LLMUsageBuffer,
)


class TestLLMUsageBufferKeys:
    """Tests for key and field generation."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.client = MagicMock()
        return redis

    @pytest.fixture
    def buffer(self, mock_redis):
        return LLMUsageBuffer(mock_redis)

    def test_make_bucket_key(self, buffer):
        """Test _make_bucket_key generates correct key format."""
        dt = datetime(2026, 3, 29, 14, 30, 0, tzinfo=UTC)
        key = buffer._make_bucket_key(dt)
        assert key == "llm:usage:2026032914"

    def test_make_bucket_key_midnight(self, buffer):
        """Test _make_bucket_key at midnight."""
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        key = buffer._make_bucket_key(dt)
        assert key == "llm:usage:2026010100"

    def test_make_field_name(self, buffer):
        """Test _make_field_name generates correct field format."""
        field = buffer._make_field_name("chat::aiping::qwen-plus", "classifier", "count")
        assert field == "chat::aiping::qwen-plus::classifier::count"

    def test_redis_key_prefix(self):
        """Test REDIS_KEY_PREFIX constant."""
        assert REDIS_KEY_PREFIX == "llm:usage"

    def test_default_ttl(self):
        """Test DEFAULT_TTL_SECONDS constant."""
        assert DEFAULT_TTL_SECONDS == 7200


class TestLLMUsageBufferAccumulate:
    """Tests for LLMUsageBuffer.accumulate()."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.client = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.hincrby = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[1] * 8)

        redis.client.pipeline = MagicMock(return_value=mock_pipeline)
        redis.client.hgetall = AsyncMock(return_value={})

        return redis

    @pytest.fixture
    def buffer(self, mock_redis):
        return LLMUsageBuffer(mock_redis)

    @pytest.mark.asyncio
    async def test_accumulate_success_event(self, buffer, mock_redis):
        """Test accumulate() with successful event."""
        event = LLMUsageEvent(
            label="chat::aiping::qwen-plus",
            call_point="classifier",
            llm_type="chat",
            provider="aiping",
            model="qwen-plus",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=1234.5,
            success=True,
        )

        await buffer.accumulate(event)

        mock_redis.client.pipeline.assert_called_once()
        pipeline = mock_redis.client.pipeline.return_value

        bucket_key = buffer._make_bucket_key(event.timestamp)
        field_prefix = "chat::aiping::qwen-plus::classifier"

        expected_calls = [
            (bucket_key, f"{field_prefix}::count", 1),
            (bucket_key, f"{field_prefix}::input_tok", 100),
            (bucket_key, f"{field_prefix}::output_tok", 50),
            (bucket_key, f"{field_prefix}::total_tok", 150),
            (bucket_key, f"{field_prefix}::latency_ms", 1234),
            (bucket_key, f"{field_prefix}::success", 1),
            (bucket_key, f"{field_prefix}::failure", 0),
        ]

        hincrby_calls = pipeline.hincrby.call_args_list
        assert len(hincrby_calls) == 7

        for i, expected in enumerate(expected_calls):
            actual = hincrby_calls[i][0]
            assert actual == expected, f"hincrby call {i} mismatch"

        pipeline.expire.assert_called_once_with(bucket_key, DEFAULT_TTL_SECONDS)
        pipeline.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_accumulate_failure_event(self, buffer, mock_redis):
        """Test accumulate() with failed event increments failure counter."""
        event = LLMUsageEvent(
            label="embedding::openai::text-embedding-3-small",
            call_point="vectorize",
            llm_type="embedding",
            provider="openai",
            model="text-embedding-3-small",
            tokens=TokenUsage(input_tokens=500, output_tokens=0, total_tokens=500),
            latency_ms=2000.0,
            success=False,
            error_type="RateLimitError",
        )

        await buffer.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        hincrby_calls = pipeline.hincrby.call_args_list

        success_call = hincrby_calls[5][0]
        failure_call = hincrby_calls[6][0]

        assert success_call[2] == 0
        assert failure_call[2] == 1

    @pytest.mark.asyncio
    async def test_accumulate_custom_ttl(self, mock_redis):
        """Test buffer uses custom TTL."""
        custom_ttl = 3600
        buf = LLMUsageBuffer(mock_redis, ttl_seconds=custom_ttl)

        event = LLMUsageEvent(
            label="chat::anthropic::claude-3",
            call_point="analyzer",
            tokens=TokenUsage(),
            success=True,
        )

        await buf.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        expire_call = pipeline.expire.call_args[0]
        assert expire_call[1] == custom_ttl

    @pytest.mark.asyncio
    async def test_accumulate_handles_redis_error_gracefully(self, buffer, mock_redis):
        """Test accumulate() does not raise on Redis error."""
        pipeline = mock_redis.client.pipeline.return_value
        pipeline.execute = AsyncMock(side_effect=ConnectionError("Redis connection lost"))

        event = LLMUsageEvent(
            label="chat::openai::gpt-4",
            call_point="test",
            tokens=TokenUsage(),
            success=True,
        )

        await buffer.accumulate(event)

    @pytest.mark.asyncio
    async def test_accumulate_handles_pipeline_creation_error(self, buffer, mock_redis):
        """Test accumulate() does not raise on pipeline creation error."""
        mock_redis.client.pipeline = MagicMock(side_effect=RuntimeError("Pipeline error"))

        event = LLMUsageEvent(
            label="chat::test::model",
            call_point="test",
            tokens=TokenUsage(),
            success=True,
        )

        await buffer.accumulate(event)

    @pytest.mark.asyncio
    async def test_accumulate_latency_truncation(self, buffer, mock_redis):
        """Test accumulate() truncates latency_ms to integer."""
        event = LLMUsageEvent(
            label="chat::test::model",
            call_point="test",
            tokens=TokenUsage(),
            latency_ms=1234.567,
            success=True,
        )

        await buffer.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        latency_call = pipeline.hincrby.call_args_list[4][0]
        assert latency_call[2] == 1234

    @pytest.mark.asyncio
    async def test_accumulate_with_zero_tokens(self, buffer, mock_redis):
        """Test accumulate() handles zero token usage."""
        event = LLMUsageEvent(
            label="chat::test::model",
            call_point="test",
            tokens=TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            latency_ms=50.0,
            success=True,
        )

        await buffer.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        hincrby_calls = pipeline.hincrby.call_args_list

        assert hincrby_calls[1][0][2] == 0  # input_tok
        assert hincrby_calls[2][0][2] == 0  # output_tok
        assert hincrby_calls[3][0][2] == 0  # total_tok


class TestLLMUsageBufferGetBucketData:
    """Tests for LLMUsageBuffer.get_bucket_data()."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.client = MagicMock()
        redis.client.hgetall = AsyncMock(return_value={})
        return redis

    @pytest.fixture
    def buffer(self, mock_redis):
        return LLMUsageBuffer(mock_redis)

    @pytest.mark.asyncio
    async def test_get_bucket_data_returns_data(self, buffer, mock_redis):
        """Test get_bucket_data() returns hash data."""
        expected_data = {
            "chat::test::model::test::count": "10",
            "chat::test::model::test::input_tok": "1000",
        }
        mock_redis.client.hgetall = AsyncMock(return_value=expected_data)

        result = await buffer.get_bucket_data("llm:usage:2026032914")

        assert result == expected_data
        mock_redis.client.hgetall.assert_called_once_with("llm:usage:2026032914")

    @pytest.mark.asyncio
    async def test_get_bucket_data_returns_empty_on_error(self, buffer, mock_redis):
        """Test get_bucket_data() returns empty dict on error."""
        mock_redis.client.hgetall = AsyncMock(side_effect=ConnectionError("Redis error"))

        result = await buffer.get_bucket_data("llm:usage:2026032914")

        assert result == {}


class TestLLMUsageBufferGetCurrentBucketKey:
    """Tests for LLMUsageBuffer.get_current_bucket_key()."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.client = MagicMock()
        return redis

    @pytest.fixture
    def buffer(self, mock_redis):
        return LLMUsageBuffer(mock_redis)

    @pytest.mark.asyncio
    async def test_get_current_bucket_key(self, buffer):
        """Test get_current_bucket_key() returns correctly formatted key."""
        with patch("modules.storage.llm_usage_buffer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 29, 15, 0, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            key = await buffer.get_current_bucket_key()

            assert key == "llm:usage:2026032915"


class TestLLMUsageBufferMultipleEvents:
    """Tests for accumulating multiple events."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.client = MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.hincrby = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[1] * 8)

        redis.client.pipeline = MagicMock(return_value=mock_pipeline)
        redis.client.hgetall = AsyncMock(return_value={})

        return redis

    @pytest.fixture
    def buffer(self, mock_redis):
        return LLMUsageBuffer(mock_redis)

    @pytest.mark.asyncio
    async def test_accumulate_multiple_events_same_bucket(self, buffer, mock_redis):
        """Test accumulating multiple events to the same bucket."""
        events = [
            LLMUsageEvent(
                label="chat::test::model",
                call_point="test",
                tokens=TokenUsage(input_tokens=100, output_tokens=50),
                latency_ms=100.0,
                success=True,
            ),
            LLMUsageEvent(
                label="chat::test::model",
                call_point="test",
                tokens=TokenUsage(input_tokens=200, output_tokens=100),
                latency_ms=200.0,
                success=False,
            ),
        ]

        for event in events:
            await buffer.accumulate(event)

        assert mock_redis.client.pipeline.call_count == 2

    @pytest.mark.asyncio
    async def test_accumulate_different_labels_separate_fields(self, buffer, mock_redis):
        """Test different labels create separate hash fields."""
        events = [
            LLMUsageEvent(
                label="chat::provider1::model1",
                call_point="test",
                tokens=TokenUsage(),
                success=True,
            ),
            LLMUsageEvent(
                label="chat::provider2::model2",
                call_point="test",
                tokens=TokenUsage(),
                success=True,
            ),
        ]

        for event in events:
            await buffer.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        hincrby_calls = pipeline.hincrby.call_args_list

        first_label_field = hincrby_calls[0][0][1]
        second_label_field = hincrby_calls[7][0][1]

        assert "provider1::model1" in first_label_field
        assert "provider2::model2" in second_label_field
