"""Unit tests for deduplicator module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from modules.collector.deduplicator import Deduplicator


class TestDeduplicator:
    """Tests for Deduplicator."""

    def test_deduplicator_initialization(self):
        """Test deduplicator initializes correctly."""
        mock_redis = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)

        assert dedup._redis is mock_redis
        assert dedup._repo is mock_repo
        assert dedup.DEDUP_KEY == "crawl:dedup"

    @pytest.mark.asyncio
    async def test_dedup_with_no_items(self):
        """Test deduplication with empty list."""
        mock_redis = MagicMock()
        mock_repo = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=MagicMock())

        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)

        result = await dedup.dedup([])

        assert result == []
        mock_redis.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_hash_function(self):
        """Test URL hashing function."""
        mock_redis = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)

        # Test that same URL produces same hash
        url = "https://example.com/article"
        hash1 = dedup._hash(url)
        hash2 = dedup._hash(url)

        assert hash1 == hash2
        assert len(hash1) == 16  # sha256[:16]

        # Different URLs should produce different hashes
        hash3 = dedup._hash("https://example.com/different")
        assert hash1 != hash3
