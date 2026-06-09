# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SentimentAggregator."""

from __future__ import annotations

from datetime import date

import pytest

from modules.analytics.aggregator import SentimentAggregator


class TestSentimentAggregator:
    """Tests for SentimentAggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create a SentimentAggregator instance."""
        return SentimentAggregator()

    @pytest.mark.asyncio
    async def test_aggregate_returns_list(self, aggregator):
        """Test aggregate returns a list."""
        result = await aggregator.aggregate("community_1", date(2026, 1, 1), date(2026, 1, 7))
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_aggregate_returns_empty_by_default(self, aggregator):
        """Test aggregate returns empty list by default."""
        result = await aggregator.aggregate("community_1", date(2026, 1, 1), date(2026, 1, 7))
        assert result == []

    @pytest.mark.asyncio
    async def test_aggregate_with_same_start_end_date(self, aggregator):
        """Test aggregate with same start and end date."""
        result = await aggregator.aggregate("community_1", date(2026, 6, 1), date(2026, 6, 1))
        assert result == []

    @pytest.mark.asyncio
    async def test_aggregate_accepts_string_community_id(self, aggregator):
        """Test aggregate accepts string community_id."""
        result = await aggregator.aggregate("any_id", date(2026, 1, 1), date(2026, 1, 31))
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_aggregate_reverse_date_range(self, aggregator):
        """Test aggregate with reversed date range (start > end)."""
        result = await aggregator.aggregate("community_1", date(2026, 6, 7), date(2026, 6, 1))
        assert isinstance(result, list)
