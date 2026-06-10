# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SentimentAggregator."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

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


class TestSentimentAggregatorWithPool:
    """Tests for SentimentAggregator with database pool."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock RelationalPool."""
        pool = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        pool.session_context.return_value = mock_session
        return pool

    @pytest.fixture
    def aggregator_with_pool(self, mock_pool):
        """Create a SentimentAggregator with pool."""
        return SentimentAggregator(pool=mock_pool)

    @pytest.mark.asyncio
    async def test_aggregate_returns_community_sentiment_series(
        self, aggregator_with_pool, mock_pool
    ):
        """Test aggregate returns daily sentiment series for a community."""
        # Mock database rows
        mock_row1 = MagicMock()
        mock_row1.date = date(2026, 1, 1)
        mock_row1.avg_sentiment = 0.6
        mock_row1.article_count = 5

        mock_row2 = MagicMock()
        mock_row2.date = date(2026, 1, 2)
        mock_row2.avg_sentiment = 0.7
        mock_row2.article_count = 3

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row1, mock_row2]

        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await aggregator_with_pool.aggregate(
            "community_1", date(2026, 1, 1), date(2026, 1, 2)
        )

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["date"] == date(2026, 1, 1)
        assert result[0]["avg_sentiment"] == 0.6
        assert result[0]["article_count"] == 5

    @pytest.mark.asyncio
    async def test_aggregate_queries_database(self, aggregator_with_pool, mock_pool):
        """Test aggregate queries the database."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.execute = AsyncMock(return_value=mock_result)

        await aggregator_with_pool.aggregate("community_1", date(2026, 1, 1), date(2026, 1, 7))

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregate_handles_db_error(self, aggregator_with_pool, mock_pool):
        """Test aggregate handles database errors gracefully."""
        mock_session = mock_pool.session_context.return_value.__aenter__.return_value
        mock_session.execute = AsyncMock(side_effect=Exception("DB error"))

        result = await aggregator_with_pool.aggregate(
            "community_1", date(2026, 1, 1), date(2026, 1, 7)
        )

        assert result == []
