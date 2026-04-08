# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for analytics LLM usage aggregator."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time

from modules.analytics.llm_usage.aggregator import (
    REDIS_KEY_PREFIX,
    _aggregate_metric,
    _parse_field,
    _parse_label,
    aggregate_usage_data,
    flush_usage_buffer,
)


class TestParseField:
    """Tests for _parse_field helper."""

    def test_parse_valid_field(self):
        """Test parsing a valid field string."""
        result = _parse_field("chat::openai::gpt-4::classifier::count")
        assert result == ("chat::openai::gpt-4", "classifier", "count")

    def test_parse_field_with_colons_in_label(self):
        """Test parsing field with multiple colons in label."""
        result = _parse_field("embedding::anthropic::claude::reranker::input_tok")
        assert result == ("embedding::anthropic::claude", "reranker", "input_tok")

    def test_parse_field_with_complex_label(self):
        """Test parsing field with complex label containing many colons."""
        result = _parse_field("chat::provider::model::call_point::metric")
        assert result == ("chat::provider::model", "call_point", "metric")

    def test_parse_field_returns_none_for_invalid(self):
        """Test parsing returns None for invalid field format."""
        result = _parse_field("invalid_field")
        assert result is None

    def test_parse_field_returns_none_for_missing_parts(self):
        """Test parsing returns None when parts are missing."""
        result = _parse_field("label::call_point")
        assert result is None

    def test_parse_field_returns_none_for_empty_string(self):
        """Test parsing returns None for empty string."""
        result = _parse_field("")
        assert result is None

    def test_parse_field_preserves_label_structure(self):
        """Test that label part is preserved as-is."""
        result = _parse_field("a::b::c::d::e")
        assert result == ("a::b::c", "d", "e")


class TestParseLabel:
    """Tests for _parse_label helper."""

    def test_parse_label_with_three_parts(self):
        """Test parsing label with llm_type, provider, model."""
        result = _parse_label("chat::openai::gpt-4")
        assert result == ("chat", "openai", "gpt-4")

    def test_parse_label_with_two_parts(self):
        """Test parsing label with provider::model format."""
        result = _parse_label("anthropic::claude-3")
        assert result == ("chat", "anthropic", "claude-3")

    def test_parse_label_with_single_part(self):
        """Test parsing label with single part returns defaults."""
        result = _parse_label("unknown-label")
        assert result == ("chat", "unknown", "unknown-label")

    def test_parse_label_embedding_type(self):
        """Test parsing embedding type label."""
        result = _parse_label("embedding::openai::text-embedding-3")
        assert result == ("embedding", "openai", "text-embedding-3")

    def test_parse_label_rerank_type(self):
        """Test parsing rerank type label."""
        result = _parse_label("rerank::cohere::rerank-v3")
        assert result == ("rerank", "cohere", "rerank-v3")

    def test_parse_label_empty_string(self):
        """Test parsing empty label."""
        result = _parse_label("")
        assert result == ("chat", "unknown", "")


class TestAggregateMetric:
    """Tests for _aggregate_metric helper."""

    def test_aggregate_count(self):
        """Test aggregating count metric."""
        agg = {"count": 0}
        _aggregate_metric(agg, "count", 5)
        assert agg["count"] == 5

    def test_aggregate_count_accumulates(self):
        """Test count metric accumulates correctly."""
        agg = {"count": 10}
        _aggregate_metric(agg, "count", 3)
        assert agg["count"] == 13

    def test_aggregate_input_tok(self):
        """Test aggregating input_tok metric."""
        agg = {"input_tok": 0}
        _aggregate_metric(agg, "input_tok", 1000)
        assert agg["input_tok"] == 1000

    def test_aggregate_output_tok(self):
        """Test aggregating output_tok metric."""
        agg = {"output_tok": 500}
        _aggregate_metric(agg, "output_tok", 200)
        assert agg["output_tok"] == 700

    def test_aggregate_total_tok(self):
        """Test aggregating total_tok metric."""
        agg = {"total_tok": 0}
        _aggregate_metric(agg, "total_tok", 1200)
        assert agg["total_tok"] == 1200

    def test_aggregate_latency_ms(self):
        """Test aggregating latency_ms metric converts to float."""
        agg = {"latency_ms": 0.0}
        _aggregate_metric(agg, "latency_ms", 150)
        assert agg["latency_ms"] == 150.0

    def test_aggregate_latency_ms_accumulates(self):
        """Test latency_ms accumulates as float."""
        agg = {"latency_ms": 100.0}
        _aggregate_metric(agg, "latency_ms", 50)
        assert agg["latency_ms"] == 150.0

    def test_aggregate_success(self):
        """Test aggregating success metric."""
        agg = {"success": 0}
        _aggregate_metric(agg, "success", 10)
        assert agg["success"] == 10

    def test_aggregate_failure(self):
        """Test aggregating failure metric."""
        agg = {"failure": 0}
        _aggregate_metric(agg, "failure", 2)
        assert agg["failure"] == 2

    def test_aggregate_unknown_metric_does_nothing(self):
        """Test aggregating unknown metric is ignored."""
        agg = {"count": 5}
        _aggregate_metric(agg, "unknown_metric", 100)
        assert agg["count"] == 5


class TestAggregateUsageData:
    """Tests for aggregate_usage_data function."""

    def test_aggregate_empty_data(self):
        """Test aggregating empty data returns empty dict."""
        result = aggregate_usage_data({})
        assert result == {}

    def test_aggregate_single_group(self):
        """Test aggregating data for a single label/call_point group."""
        data = {
            "chat::openai::gpt-4::classifier::count": "5",
            "chat::openai::gpt-4::classifier::input_tok": "1000",
            "chat::openai::gpt-4::classifier::output_tok": "500",
            "chat::openai::gpt-4::classifier::total_tok": "1500",
            "chat::openai::gpt-4::classifier::latency_ms": "150",
            "chat::openai::gpt-4::classifier::success": "4",
            "chat::openai::gpt-4::classifier::failure": "1",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        assert key in result
        assert result[key]["count"] == 5
        assert result[key]["input_tok"] == 1000
        assert result[key]["output_tok"] == 500
        assert result[key]["total_tok"] == 1500
        assert result[key]["latency_ms"] == 150.0
        assert result[key]["success"] == 4
        assert result[key]["failure"] == 1
        assert result[key]["llm_type"] == "chat"
        assert result[key]["provider"] == "openai"
        assert result[key]["model"] == "gpt-4"

    def test_aggregate_multiple_groups(self):
        """Test aggregating data for multiple label/call_point groups."""
        data = {
            "chat::openai::gpt-4::classifier::count": "10",
            "chat::openai::gpt-4::classifier::success": "10",
            "chat::anthropic::claude::analyzer::count": "5",
            "chat::anthropic::claude::analyzer::success": "5",
        }
        result = aggregate_usage_data(data)

        assert len(result) == 2
        key1 = ("chat::openai::gpt-4", "classifier")
        key2 = ("chat::anthropic::claude", "analyzer")
        assert result[key1]["count"] == 10
        assert result[key2]["count"] == 5

    def test_aggregate_accumulates_values(self):
        """Test aggregating accumulates values correctly."""
        data = {
            "chat::openai::gpt-4::classifier::count": "3",
            "chat::openai::gpt-4::classifier::input_tok": "100",
        }
        result = aggregate_usage_data(data)
        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["count"] == 3
        assert result[key]["input_tok"] == 100

    def test_aggregate_skips_invalid_fields(self):
        """Test that invalid fields are skipped."""
        data = {
            "chat::openai::gpt-4::classifier::count": "5",
            "invalid_field": "100",
            "also_invalid": "200",
        }
        result = aggregate_usage_data(data)

        assert len(result) == 1
        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["count"] == 5

    def test_aggregate_skips_non_integer_values(self):
        """Test that non-integer values are skipped."""
        data = {
            "chat::openai::gpt-4::classifier::count": "5",
            "chat::openai::gpt-4::classifier::input_tok": "not_a_number",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        assert result[key]["count"] == 5
        assert result[key]["input_tok"] == 0  # Default, skipped invalid value

    def test_aggregate_with_two_part_label(self):
        """Test aggregating with two-part label (provider::model)."""
        data = {
            "anthropic::claude::classifier::count": "10",
        }
        result = aggregate_usage_data(data)

        key = ("anthropic::claude", "classifier")
        assert result[key]["llm_type"] == "chat"
        assert result[key]["provider"] == "anthropic"
        assert result[key]["model"] == "claude"

    def test_aggregate_with_single_part_label(self):
        """Test aggregating with single-part label."""
        data = {
            "unknown_model::classifier::count": "5",
        }
        result = aggregate_usage_data(data)

        key = ("unknown_model", "classifier")
        assert result[key]["llm_type"] == "chat"
        assert result[key]["provider"] == "unknown"
        assert result[key]["model"] == "unknown_model"

    def test_aggregate_default_values(self):
        """Test that default values are set correctly."""
        data = {
            "chat::openai::gpt-4::classifier::count": "1",
        }
        result = aggregate_usage_data(data)

        key = ("chat::openai::gpt-4", "classifier")
        agg = result[key]
        assert agg["count"] == 1
        assert agg["input_tok"] == 0
        assert agg["output_tok"] == 0
        assert agg["total_tok"] == 0
        assert agg["latency_ms"] == 0.0
        assert agg["success"] == 0
        assert agg["failure"] == 0

    def test_aggregate_embedding_type(self):
        """Test aggregating embedding type data."""
        data = {
            "embedding::openai::text-embedding-3::vectorizer::count": "20",
            "embedding::openai::text-embedding-3::vectorizer::input_tok": "5000",
        }
        result = aggregate_usage_data(data)

        key = ("embedding::openai::text-embedding-3", "vectorizer")
        assert result[key]["llm_type"] == "embedding"
        assert result[key]["provider"] == "openai"
        assert result[key]["model"] == "text-embedding-3"

    def test_aggregate_rerank_type(self):
        """Test aggregating rerank type data."""
        data = {
            "rerank::cohere::rerank-v3::search::count": "15",
        }
        result = aggregate_usage_data(data)

        key = ("rerank::cohere::rerank-v3", "search")
        assert result[key]["llm_type"] == "rerank"
        assert result[key]["provider"] == "cohere"
        assert result[key]["model"] == "rerank-v3"


class TestFlushUsageBuffer:
    """Tests for flush_usage_buffer function."""

    @pytest.fixture
    def mock_cache(self):
        """Create a mock CachePool."""
        cache = MagicMock()
        cache.scan = AsyncMock()
        cache.hgetall = AsyncMock()
        cache.delete = AsyncMock()
        return cache

    @pytest.fixture
    def mock_relational_pool(self):
        """Create a mock RelationalPool."""
        return MagicMock()

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_no_keys_returns_zero(self, mock_cache, mock_relational_pool):
        """Test flush returns (0, 0) when no keys found."""
        mock_cache.scan.return_value = (0, [])

        result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (0, 0)
        mock_cache.scan.assert_called_once()

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_excludes_current_hour(self, mock_cache, mock_relational_pool):
        """Test flush excludes current hour bucket."""
        current_hour_key = f"{REDIS_KEY_PREFIX}:2026040614"

        # Return current hour key but it should be filtered out
        mock_cache.scan.return_value = (0, [current_hour_key])

        result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (0, 0)

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_processes_single_key(self, mock_cache, mock_relational_pool):
        """Test flush processes a single key successfully."""
        past_hour_key = f"{REDIS_KEY_PREFIX}:2026040510"

        mock_cache.scan.return_value = (0, [past_hour_key])

        # Mock hgetall to return usage data
        mock_cache.hgetall.return_value = {
            "chat::openai::gpt-4::classifier::count": "5",
            "chat::openai::gpt-4::classifier::success": "5",
        }

        # Mock LLMUsageRepo methods
        mock_repo = MagicMock()
        mock_repo.get_latency_bounds = AsyncMock(return_value=(100.0, 500.0))
        mock_repo.upsert_hourly = AsyncMock()

        with patch(
            "modules.analytics.llm_usage.repo.LLMUsageRepo",
            return_value=mock_repo,
        ):
            result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (1, 0)
        mock_cache.delete.assert_called_once_with(past_hour_key)

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_deletes_empty_hash(self, mock_cache, mock_relational_pool):
        """Test flush deletes empty hash without processing."""
        past_hour_key = f"{REDIS_KEY_PREFIX}:2026040510"

        mock_cache.scan.return_value = (0, [past_hour_key])
        mock_cache.hgetall.return_value = {}

        result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (0, 0)
        mock_cache.delete.assert_called_once_with(past_hour_key)

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_handles_multiple_keys(self, mock_cache, mock_relational_pool):
        """Test flush processes multiple keys."""
        keys = [
            f"{REDIS_KEY_PREFIX}:2026040510",
            f"{REDIS_KEY_PREFIX}:2026040511",
        ]

        mock_cache.scan.return_value = (0, keys)

        # Return data for both keys
        mock_cache.hgetall.side_effect = [
            {"chat::openai::gpt-4::classifier::count": "5"},
            {"chat::anthropic::claude::analyzer::count": "3"},
        ]

        mock_repo = MagicMock()
        mock_repo.get_latency_bounds = AsyncMock(return_value=(0.0, 0.0))
        mock_repo.upsert_hourly = AsyncMock()

        with patch(
            "modules.analytics.llm_usage.repo.LLMUsageRepo",
            return_value=mock_repo,
        ):
            result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (2, 0)
        assert mock_cache.delete.call_count == 2

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_handles_scan_pagination(self, mock_cache, mock_relational_pool):
        """Test flush handles SCAN pagination correctly."""
        keys_page1 = [f"{REDIS_KEY_PREFIX}:2026040510"]
        keys_page2 = [f"{REDIS_KEY_PREFIX}:2026040511"]

        # First scan returns cursor 100, second returns cursor 0
        mock_cache.scan.side_effect = [
            (100, keys_page1),
            (0, keys_page2),
        ]

        mock_cache.hgetall.side_effect = [
            {"chat::openai::gpt-4::classifier::count": "5"},
            {"chat::anthropic::claude::analyzer::count": "3"},
        ]

        mock_repo = MagicMock()
        mock_repo.get_latency_bounds = AsyncMock(return_value=(0.0, 0.0))
        mock_repo.upsert_hourly = AsyncMock()

        with patch(
            "modules.analytics.llm_usage.repo.LLMUsageRepo",
            return_value=mock_repo,
        ):
            result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (2, 0)
        assert mock_cache.scan.call_count == 2

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_counts_errors(self, mock_cache, mock_relational_pool):
        """Test flush counts errors when processing fails."""
        past_hour_key = f"{REDIS_KEY_PREFIX}:2026040510"

        mock_cache.scan.return_value = (0, [past_hour_key])
        mock_cache.hgetall.return_value = {
            "chat::openai::gpt-4::classifier::count": "5",
        }

        mock_repo = MagicMock()
        mock_repo.get_latency_bounds = AsyncMock(side_effect=Exception("DB error"))

        with patch(
            "modules.analytics.llm_usage.repo.LLMUsageRepo",
            return_value=mock_repo,
        ):
            result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (0, 1)

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_handles_invalid_key_format(self, mock_cache, mock_relational_pool):
        """Test flush handles keys with invalid time bucket format."""
        invalid_key = f"{REDIS_KEY_PREFIX}:invalid_format"

        mock_cache.scan.return_value = (0, [invalid_key])
        mock_cache.hgetall.return_value = {"data": "value"}

        result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        # Invalid key format causes exception, counted as error
        assert result == (0, 1)

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_calls_upsert_with_correct_params(self, mock_cache, mock_relational_pool):
        """Test flush calls upsert_hourly with correct parameters."""
        past_hour_key = f"{REDIS_KEY_PREFIX}:2026040510"
        expected_time_bucket = datetime(2026, 4, 5, 10, 0, 0, tzinfo=UTC)

        mock_cache.scan.return_value = (0, [past_hour_key])
        mock_cache.hgetall.return_value = {
            "chat::openai::gpt-4::classifier::count": "10",
            "chat::openai::gpt-4::classifier::input_tok": "2000",
            "chat::openai::gpt-4::classifier::output_tok": "1000",
            "chat::openai::gpt-4::classifier::total_tok": "3000",
            "chat::openai::gpt-4::classifier::latency_ms": "500",
            "chat::openai::gpt-4::classifier::success": "9",
            "chat::openai::gpt-4::classifier::failure": "1",
        }

        mock_repo = MagicMock()
        mock_repo.get_latency_bounds = AsyncMock(return_value=(50.0, 100.0))
        mock_repo.upsert_hourly = AsyncMock()

        with patch(
            "modules.analytics.llm_usage.repo.LLMUsageRepo",
            return_value=mock_repo,
        ):
            result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (1, 0)
        mock_repo.upsert_hourly.assert_called_once()
        call_kwargs = mock_repo.upsert_hourly.call_args.kwargs
        assert call_kwargs["time_bucket"] == expected_time_bucket
        assert call_kwargs["label"] == "chat::openai::gpt-4"
        assert call_kwargs["call_point"] == "classifier"
        assert call_kwargs["llm_type"] == "chat"
        assert call_kwargs["provider"] == "openai"
        assert call_kwargs["model"] == "gpt-4"
        assert call_kwargs["call_count"] == 10
        assert call_kwargs["input_tokens_sum"] == 2000
        assert call_kwargs["output_tokens_sum"] == 1000
        assert call_kwargs["total_tokens_sum"] == 3000
        assert call_kwargs["latency_sum"] == 500.0
        assert call_kwargs["latency_min"] == 50.0
        assert call_kwargs["latency_max"] == 100.0
        assert call_kwargs["success_count"] == 9
        assert call_kwargs["failure_count"] == 1

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_processes_multiple_groups_per_key(self, mock_cache, mock_relational_pool):
        """Test flush processes multiple groups within single key."""
        past_hour_key = f"{REDIS_KEY_PREFIX}:2026040510"

        mock_cache.scan.return_value = (0, [past_hour_key])
        mock_cache.hgetall.return_value = {
            "chat::openai::gpt-4::classifier::count": "5",
            "chat::openai::gpt-4::classifier::success": "5",
            "chat::anthropic::claude::analyzer::count": "3",
            "chat::anthropic::claude::analyzer::success": "3",
        }

        mock_repo = MagicMock()
        mock_repo.get_latency_bounds = AsyncMock(return_value=(0.0, 0.0))
        mock_repo.upsert_hourly = AsyncMock()

        with patch(
            "modules.analytics.llm_usage.repo.LLMUsageRepo",
            return_value=mock_repo,
        ):
            result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        assert result == (1, 0)
        # Two groups, two upsert calls
        assert mock_repo.upsert_hourly.call_count == 2

    @pytest.mark.asyncio
    @freeze_time("2026-04-06 14:30:00", tz_offset=0)
    async def test_flush_handles_partial_errors(self, mock_cache, mock_relational_pool):
        """Test flush continues processing after errors."""
        keys = [
            f"{REDIS_KEY_PREFIX}:2026040510",
            f"{REDIS_KEY_PREFIX}:2026040511",
        ]

        mock_cache.scan.return_value = (0, keys)

        # First key succeeds, second fails
        mock_cache.hgetall.side_effect = [
            {"chat::openai::gpt-4::classifier::count": "5"},
            Exception("Redis error"),
        ]

        mock_repo = MagicMock()
        mock_repo.get_latency_bounds = AsyncMock(return_value=(0.0, 0.0))
        mock_repo.upsert_hourly = AsyncMock()

        with patch(
            "modules.analytics.llm_usage.repo.LLMUsageRepo",
            return_value=mock_repo,
        ):
            result = await flush_usage_buffer(mock_cache, mock_relational_pool)

        # First processed, second error
        assert result == (1, 1)


class TestRedisKeyPrefix:
    """Tests for REDIS_KEY_PREFIX constant."""

    def test_redis_key_prefix_value(self):
        """Test REDIS_KEY_PREFIX has correct value."""
        assert REDIS_KEY_PREFIX == "llm:usage"

    def test_redis_key_prefix_from_constants(self):
        """Test REDIS_KEY_PREFIX derives from RedisKeys."""
        from core.constants import RedisKeys

        assert RedisKeys.LLM_USAGE_PREFIX.rstrip(":") == REDIS_KEY_PREFIX
