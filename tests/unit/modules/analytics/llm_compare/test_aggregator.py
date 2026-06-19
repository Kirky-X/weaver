# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for modules.analytics.llm_compare.aggregator module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.analytics.llm_compare.aggregator import (
    aggregate_compare_data,
    flush_compare_buffer,
)


class TestAggregateCompareData:
    """Test aggregate_compare_data function."""

    def test_aggregate_empty_data(self):
        """Test aggregate with empty data."""
        result = aggregate_compare_data({})

        assert result == {}

    def test_aggregate_single_entry(self):
        """Test aggregate with single entry."""
        data = {
            "chat::gpt-4::claude-3::count": "10",
            "chat::gpt-4::claude-3::primary_latency_sum": "5000",
            "chat::gpt-4::claude-3::candidate_latency_sum": "4500",
            "chat::gpt-4::claude-3::primary_success": "10",
            "chat::gpt-4::claude-3::candidate_success": "10",
        }

        result = aggregate_compare_data(data)

        assert ("chat", "gpt-4", "claude-3") in result
        assert result[("chat", "gpt-4", "claude-3")]["count"] == 10
        assert result[("chat", "gpt-4", "claude-3")]["primary_latency_sum"] == 5000

    def test_aggregate_multiple_entries(self):
        """Test aggregate with multiple entries."""
        data = {
            "chat::gpt-4::claude-3::count": "10",
            "chat::gpt-4::claude-3::primary_latency_sum": "5000",
            "chat::model-a::model-b::count": "5",
            "chat::model-a::model-b::primary_latency_sum": "2500",
        }

        result = aggregate_compare_data(data)

        assert len(result) == 2
        assert result[("chat", "gpt-4", "claude-3")]["count"] == 10
        assert result[("chat", "model-a", "model-b")]["count"] == 5

    def test_aggregate_ignores_invalid_field_format(self):
        """Test aggregate ignores invalid field formats."""
        data = {
            "chat::gpt-4::claude-3::count": "10",
            "invalid_field": "5",  # Missing parts
            "also::invalid": "3",  # Not enough parts
        }

        result = aggregate_compare_data(data)

        assert len(result) == 1
        assert result[("chat", "gpt-4", "claude-3")]["count"] == 10

    def test_aggregate_ignores_invalid_values(self):
        """Test aggregate ignores non-integer values."""
        data = {
            "chat::gpt-4::claude-3::count": "10",
            "chat::gpt-4::claude-3::primary_latency_sum": "not_a_number",
        }

        result = aggregate_compare_data(data)

        # Count should still be aggregated
        assert result[("chat", "gpt-4", "claude-3")]["count"] == 10
        # Latency sum should be 0 (ignored)
        assert result[("chat", "gpt-4", "claude-3")]["primary_latency_sum"] == 0

    def test_aggregate_unknown_metric_ignored(self):
        """Test aggregate ignores unknown metrics."""
        data = {
            "chat::gpt-4::claude-3::count": "10",
            "chat::gpt-4::claude-3::unknown_metric": "100",
        }

        result = aggregate_compare_data(data)

        assert result[("chat", "gpt-4", "claude-3")]["count"] == 10


class TestFlushCompareBuffer:
    """Test flush_compare_buffer function."""

    @staticmethod
    def _async_key_iter(keys):
        """Create an async generator yielding keys (mimics CachePool.scan_iter)."""

        async def _gen():
            for key in keys:
                yield key

        return _gen()

    @pytest.fixture
    def mock_cache(self):
        """Create mock cache pool."""
        cache = AsyncMock()
        cache.scan_iter = MagicMock(return_value=self._async_key_iter([]))
        return cache

    @pytest.fixture
    def mock_relational_pool(self):
        """Create mock relational pool."""
        pool = AsyncMock()
        return pool

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self, mock_cache, mock_relational_pool):
        """Test flush with no keys to process."""
        mock_cache.scan_iter.return_value = self._async_key_iter([])

        processed, errors = await flush_compare_buffer(mock_cache, mock_relational_pool)

        assert processed == 0
        assert errors == 0

    @pytest.mark.asyncio
    async def test_flush_handles_errors(self, mock_cache, mock_relational_pool):
        """Test flush handles errors gracefully."""
        mock_cache.scan_iter.return_value = self._async_key_iter(["llm:compare:2024010100"])
        mock_cache.hgetall = AsyncMock(side_effect=Exception("Redis error"))

        processed, errors = await flush_compare_buffer(mock_cache, mock_relational_pool)

        assert processed == 0
        assert errors == 1

    @pytest.mark.asyncio
    async def test_flush_deletes_empty_hashes(self, mock_cache, mock_relational_pool):
        """Test flush deletes empty hashes without processing."""
        mock_cache.scan_iter.return_value = self._async_key_iter(["llm:compare:2024010100"])
        mock_cache.hgetall = AsyncMock(return_value={})
        mock_cache.delete = AsyncMock()

        processed, errors = await flush_compare_buffer(mock_cache, mock_relational_pool)

        assert processed == 0
        mock_cache.delete.assert_called_with("llm:compare:2024010100")

    @pytest.mark.asyncio
    async def test_flush_processes_keys(self, mock_cache, mock_relational_pool):
        """Test flush processes keys."""
        mock_cache.scan_iter.return_value = self._async_key_iter(["llm:compare:2024010100"])
        mock_cache.hgetall = AsyncMock(
            return_value={
                "chat::gpt-4::claude-3::count": "10",
            }
        )
        mock_cache.delete = AsyncMock()

        with patch("modules.analytics.llm_compare.repo.EvalCompareRepo") as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo_class.return_value = mock_repo

            processed, errors = await flush_compare_buffer(mock_cache, mock_relational_pool)

            assert processed == 1
            mock_cache.delete.assert_called()


class TestAggregatorIntegration:
    """Integration tests for aggregator."""

    def test_aggregate_real_world_data(self):
        """Test aggregate with realistic data."""
        data = {
            "chat::gpt-4::claude-3::count": "100",
            "chat::gpt-4::claude-3::primary_latency_sum": "45000",
            "chat::gpt-4::claude-3::candidate_latency_sum": "38000",
            "chat::gpt-4::claude-3::primary_success": "98",
            "chat::gpt-4::claude-3::candidate_success": "100",
            "search::gpt-4::claude-3::count": "50",
            "search::gpt-4::claude-3::primary_latency_sum": "25000",
        }

        result = aggregate_compare_data(data)

        assert len(result) == 2

        chat_key = ("chat", "gpt-4", "claude-3")
        assert result[chat_key]["count"] == 100
        assert result[chat_key]["primary_success"] == 98
        assert result[chat_key]["candidate_success"] == 100

        search_key = ("search", "gpt-4", "claude-3")
        assert result[search_key]["count"] == 50
