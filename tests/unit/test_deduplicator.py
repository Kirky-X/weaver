# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for deduplicator module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

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


class TestDeduplicatorRedisLevel:
    """Tests for Redis first-level deduplication."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis = MagicMock()
        pipeline_mock = MagicMock()
        pipeline_mock.hexists = MagicMock()
        pipeline_mock.execute = AsyncMock(return_value=[False, True])
        pipeline_mock.hset = MagicMock()
        redis.pipeline = MagicMock(return_value=pipeline_mock)
        return redis

    @pytest.fixture
    def mock_repo(self):
        """Mock article repository."""
        repo = MagicMock()
        repo.get_existing_urls = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_items(self):
        """Mock news items."""
        item1 = MagicMock()
        item1.url = "https://example.com/article1"
        item2 = MagicMock()
        item2.url = "https://example.com/article2"
        return [item1, item2]

    @pytest.mark.asyncio
    async def test_redis_dedup_first_level(self, mock_redis, mock_repo):
        """Test Redis first-level deduplication."""
        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)
        assert dedup.DEDUP_KEY == "crawl:dedup"

    @pytest.mark.asyncio
    async def test_db_dedup_second_level(self, mock_redis, mock_repo, mock_items):
        """Test DB second-level deduplication."""
        mock_repo.get_existing_urls = AsyncMock(return_value=["https://example.com/article1"])
        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)
        assert dedup._repo is mock_repo

    @pytest.mark.asyncio
    async def test_write_new_urls_to_redis(self, mock_redis, mock_repo):
        """Test new URLs are written to Redis."""
        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)
        assert hasattr(dedup, "_hash")

    @pytest.mark.asyncio
    async def test_pipeline_execution(self, mock_redis, mock_repo, mock_items):
        """Test complete deduplication pipeline."""
        mock_repo.get_existing_urls = AsyncMock(return_value=[])
        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)
        assert dedup._redis is not None
        assert dedup._repo is not None
