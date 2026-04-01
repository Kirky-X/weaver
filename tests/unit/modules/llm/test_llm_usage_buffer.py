# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMUsageBuffer module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event.bus import LLMUsageEvent
from core.llm.request import TokenUsage
from modules.analytics.llm_usage.buffer import (
    DEFAULT_TTL_SECONDS,
    REDIS_KEY_PREFIX,
    LLMUsageBuffer,
)


class TestLLMUsageBuffer:
    """Tests for LLMUsageBuffer."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock RedisClient."""
        redis = MagicMock()
        redis.client = MagicMock()

        # 创建 mock pipeline context manager
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock(return_value=None)
        mock_pipeline.hincrby = MagicMock(return_value=mock_pipeline)
        mock_pipeline.expire = MagicMock(return_value=mock_pipeline)
        mock_pipeline.execute = AsyncMock(return_value=[1] * 8)  # 7 hincrby + 1 expire

        redis.client.pipeline = MagicMock(return_value=mock_pipeline)
        redis.client.hgetall = AsyncMock(return_value={})

        return redis

    @pytest.fixture
    def buffer(self, mock_redis):
        """Create LLMUsageBuffer with mock redis."""
        return LLMUsageBuffer(mock_redis)

    def test_make_bucket_key(self, buffer):
        """Test _make_bucket_key generates correct key format."""
        dt = datetime(2026, 3, 29, 14, 30, 0, tzinfo=UTC)
        key = buffer._make_bucket_key(dt)
        assert key == "llm:usage:2026032914"

    def test_make_field_name(self, buffer):
        """Test _make_field_name generates correct field format."""
        field = buffer._make_field_name("chat::aiping::qwen-plus", "classifier", "count")
        assert field == "chat::aiping::qwen-plus::classifier::count"

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

        # 验证 pipeline 被正确调用
        mock_redis.client.pipeline.assert_called_once()
        pipeline = mock_redis.client.pipeline.return_value

        # 验证 hincrby 调用参数 - 使用动态生成的 bucket_key
        bucket_key = buffer._make_bucket_key(event.timestamp)
        field_prefix = "chat::aiping::qwen-plus::classifier"

        # 验证各指标的 hincrby 调用
        expected_calls = [
            (bucket_key, f"{field_prefix}::count", 1),
            (bucket_key, f"{field_prefix}::input_tok", 100),
            (bucket_key, f"{field_prefix}::output_tok", 50),
            (bucket_key, f"{field_prefix}::total_tok", 150),
            (bucket_key, f"{field_prefix}::latency_ms", 1234),  # int()
            (bucket_key, f"{field_prefix}::success", 1),
            (bucket_key, f"{field_prefix}::failure", 0),
        ]

        hincrby_calls = pipeline.hincrby.call_args_list
        assert len(hincrby_calls) == 7

        for i, expected in enumerate(expected_calls):
            actual = hincrby_calls[i][0]
            assert actual == expected, f"hincrby call {i} mismatch"

        # 验证 expire 被调用
        pipeline.expire.assert_called_once_with(bucket_key, DEFAULT_TTL_SECONDS)

        # 验证 execute 被调用
        pipeline.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_accumulate_failure_event(self, buffer, mock_redis):
        """Test accumulate() with failed event."""
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

        # 验证 success=0, failure=1
        success_call = hincrby_calls[5][0]
        failure_call = hincrby_calls[6][0]

        assert success_call[2] == 0  # success count
        assert failure_call[2] == 1  # failure count

    @pytest.mark.asyncio
    async def test_accumulate_sets_ttl(self, buffer, mock_redis):
        """Test accumulate() sets TTL on bucket key."""
        event = LLMUsageEvent(
            label="rerank::aiping::bge-reranker",
            call_point="search",
            tokens=TokenUsage(),
            latency_ms=100.0,
            success=True,
        )

        await buffer.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        pipeline.expire.assert_called_once()

        # 验证 TTL 参数
        expire_call = pipeline.expire.call_args[0]
        assert expire_call[1] == DEFAULT_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_accumulate_custom_ttl(self, mock_redis):
        """Test buffer uses custom TTL."""
        custom_ttl = 3600  # 1 hour
        buffer = LLMUsageBuffer(mock_redis, ttl_seconds=custom_ttl)

        event = LLMUsageEvent(
            label="chat::anthropic::claude-3",
            call_point="analyzer",
            tokens=TokenUsage(),
            success=True,
        )

        await buffer.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        expire_call = pipeline.expire.call_args[0]
        assert expire_call[1] == custom_ttl

    @pytest.mark.asyncio
    async def test_accumulate_handles_redis_error_gracefully(self, buffer, mock_redis):
        """Test accumulate() does not raise on Redis error."""
        # 让 pipeline.execute 抛出异常
        pipeline = mock_redis.client.pipeline.return_value
        pipeline.execute = AsyncMock(side_effect=ConnectionError("Redis connection lost"))

        event = LLMUsageEvent(
            label="chat::openai::gpt-4",
            call_point="test",
            tokens=TokenUsage(),
            success=True,
        )

        # 不应该抛出异常
        await buffer.accumulate(event)

        # 验证 execute 被调用
        pipeline.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_accumulate_handles_pipeline_error_gracefully(self, buffer, mock_redis):
        """Test accumulate() does not raise on pipeline creation error."""
        # 让 pipeline() 抛出异常
        mock_redis.client.pipeline = MagicMock(side_effect=RuntimeError("Pipeline error"))

        event = LLMUsageEvent(
            label="chat::test::model",
            call_point="test",
            tokens=TokenUsage(),
            success=True,
        )

        # 不应该抛出异常
        await buffer.accumulate(event)

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

        # 验证 token 相关的 hincrby 使用 0
        assert hincrby_calls[1][0][2] == 0  # input_tok
        assert hincrby_calls[2][0][2] == 0  # output_tok
        assert hincrby_calls[3][0][2] == 0  # total_tok

    @pytest.mark.asyncio
    async def test_accumulate_latency_truncation(self, buffer, mock_redis):
        """Test accumulate() truncates latency_ms to integer."""
        event = LLMUsageEvent(
            label="chat::test::model",
            call_point="test",
            tokens=TokenUsage(),
            latency_ms=1234.567,  # 带小数
            success=True,
        )

        await buffer.accumulate(event)

        pipeline = mock_redis.client.pipeline.return_value
        hincrby_calls = pipeline.hincrby.call_args_list

        # 验证 latency 被取整
        latency_call = hincrby_calls[4][0]
        assert latency_call[2] == 1234  # int(1234.567)

    @pytest.mark.asyncio
    async def test_get_bucket_data_success(self, buffer, mock_redis):
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
    async def test_get_bucket_data_on_error(self, buffer, mock_redis):
        """Test get_bucket_data() returns empty dict on error."""
        mock_redis.client.hgetall = AsyncMock(side_effect=ConnectionError("Redis error"))

        result = await buffer.get_bucket_data("llm:usage:2026032914")

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_current_bucket_key(self, buffer):
        """Test get_current_bucket_key() returns correctly formatted key."""
        # 使用 patch 控制当前时间
        with patch("modules.analytics.llm_usage.buffer.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 29, 15, 0, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            key = await buffer.get_current_bucket_key()

            assert key == "llm:usage:2026032915"

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

        # 验证 pipeline 被调用两次
        assert mock_redis.client.pipeline.call_count == 2

    @pytest.mark.asyncio
    async def test_accumulate_different_labels_separate_fields(self, buffer, mock_redis):
        """Test that different labels create separate hash fields."""
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

        # 验证两个不同的 label 产生不同的 field
        first_label_field = hincrby_calls[0][0][1]  # 第一个事件的第一个 hincrby
        second_label_field = hincrby_calls[7][0][1]  # 第二个事件的第一个 hincrby

        assert "provider1::model1" in first_label_field
        assert "provider2::model2" in second_label_field
