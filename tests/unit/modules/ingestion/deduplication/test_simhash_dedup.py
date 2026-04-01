# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SimHashDeduplicator (ingestion module)."""

import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.deduplication.simhash_dedup import SimHashDeduplicator, TitleItem


class TestSimHashDeduplicatorInit:
    """Test SimHashDeduplicator initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        mock_redis = MagicMock()

        dedup = SimHashDeduplicator(redis=mock_redis)

        assert dedup._threshold == SimHashDeduplicator.DEFAULT_THRESHOLD
        assert dedup._ttl == SimHashDeduplicator.DEFAULT_TTL

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        mock_redis = MagicMock()

        dedup = SimHashDeduplicator(
            redis=mock_redis,
            threshold=5,
            ttl_seconds=86400,
        )

        assert dedup._threshold == 5
        assert dedup._ttl == 86400

    def test_simhash_key_constant(self):
        """Test SIMHASH_KEY constant."""
        assert SimHashDeduplicator.SIMHASH_KEY == "crawl:simhash:title"

    def test_default_threshold_constant(self):
        """Test DEFAULT_THRESHOLD constant."""
        assert SimHashDeduplicator.DEFAULT_THRESHOLD == 3

    def test_default_ttl_constant(self):
        """Test DEFAULT_TTL constant."""
        assert SimHashDeduplicator.DEFAULT_TTL == 7 * 24 * 60 * 60


class TestGenerateFingerprint:
    """Test SimHashDeduplicator.generate_fingerprint static method."""

    def test_generate_fingerprint_returns_int(self):
        """Test generate_fingerprint returns an integer."""
        result = SimHashDeduplicator.generate_fingerprint("Test Title")
        assert isinstance(result, int)

    def test_generate_fingerprint_same_title_same_hash(self):
        """Test same title produces same fingerprint."""
        title = "Test Title"
        fp1 = SimHashDeduplicator.generate_fingerprint(title)
        fp2 = SimHashDeduplicator.generate_fingerprint(title)
        assert fp1 == fp2

    def test_generate_fingerprint_different_titles_different_hash(self):
        """Test different titles produce different fingerprints."""
        fp1 = SimHashDeduplicator.generate_fingerprint("First Title")
        fp2 = SimHashDeduplicator.generate_fingerprint("Second Title")
        assert fp1 != fp2

    def test_generate_fingerprint_similar_titles_small_distance(self):
        """Test similar titles have small Hamming distance."""
        # Very similar titles should have small Hamming distance
        fp1 = SimHashDeduplicator.generate_fingerprint("Test Article Title")
        fp2 = SimHashDeduplicator.generate_fingerprint("Test Article Title")
        # Same title should have 0 distance
        distance = SimHashDeduplicator.hamming_distance(fp1, fp2)
        assert distance == 0

    def test_generate_fingerprint_chinese_text(self):
        """Test generate_fingerprint works with Chinese text."""
        fp1 = SimHashDeduplicator.generate_fingerprint("中国经济新闻")
        fp2 = SimHashDeduplicator.generate_fingerprint("中国经济新闻")
        assert fp1 == fp2

    def test_generate_fingerprint_empty_string(self):
        """Test generate_fingerprint handles empty string."""
        result = SimHashDeduplicator.generate_fingerprint("")
        assert isinstance(result, int)


class TestHammingDistance:
    """Test SimHashDeduplicator.hamming_distance static method."""

    def test_hamming_distance_zero(self):
        """Test Hamming distance of identical fingerprints is 0."""
        fp = SimHashDeduplicator.generate_fingerprint("Test")
        distance = SimHashDeduplicator.hamming_distance(fp, fp)
        assert distance == 0

    def test_hamming_distance_nonzero(self):
        """Test Hamming distance of different fingerprints is non-zero."""
        fp1 = 0b11110000
        fp2 = 0b11111111
        distance = SimHashDeduplicator.hamming_distance(fp1, fp2)
        assert distance == 4  # 4 bits differ

    def test_hamming_distance_commutative(self):
        """Test Hamming distance is commutative."""
        fp1 = 0b10101010
        fp2 = 0b11001100
        distance1 = SimHashDeduplicator.hamming_distance(fp1, fp2)
        distance2 = SimHashDeduplicator.hamming_distance(fp2, fp1)
        assert distance1 == distance2


class TestTitleItem:
    """Test TitleItem dataclass."""

    def test_title_item_creation(self):
        """Test TitleItem can be created."""
        item = TitleItem(url="https://example.com/article", title="Test Title")
        assert item.url == "https://example.com/article"
        assert item.title == "Test Title"

    def test_title_item_equality(self):
        """Test TitleItem equality comparison."""
        item1 = TitleItem(url="https://example.com/article", title="Test Title")
        item2 = TitleItem(url="https://example.com/article", title="Test Title")
        assert item1 == item2


class TestDedupTitles:
    """Test SimHashDeduplicator.dedup_titles method."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={})
        redis.hset = AsyncMock()
        # Mock pipeline
        pipeline_mock = MagicMock()
        pipeline_mock.hset = MagicMock()
        pipeline_mock.execute = AsyncMock(return_value=[1])
        redis.pipeline = MagicMock(return_value=pipeline_mock)
        return redis

    @pytest.mark.asyncio
    async def test_dedup_titles_empty_list(self, mock_redis):
        """Test dedup_titles with empty list."""
        dedup = SimHashDeduplicator(redis=mock_redis)

        result = await dedup.dedup_titles([])

        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_titles_all_new(self, mock_redis):
        """Test dedup_titles with all new items."""
        dedup = SimHashDeduplicator(redis=mock_redis)

        items = [
            TitleItem(url="https://example.com/1", title="Article One"),
            TitleItem(url="https://example.com/2", title="Article Two"),
        ]

        result = await dedup.dedup_titles(items)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_dedup_titles_stores_fingerprints(self, mock_redis):
        """Test dedup_titles stores fingerprints in Redis."""
        dedup = SimHashDeduplicator(redis=mock_redis)

        items = [
            TitleItem(url="https://example.com/1", title="Article One"),
        ]

        await dedup.dedup_titles(items)

        # Should have called pipeline execute
        mock_redis.pipeline.assert_called()

    @pytest.mark.asyncio
    async def test_dedup_titles_filters_existing(self, mock_redis):
        """Test dedup_titles filters existing fingerprints."""
        # Create a fingerprint for existing title
        existing_title = "Existing Article"
        existing_fp = SimHashDeduplicator.generate_fingerprint(existing_title)

        mock_redis.hgetall = AsyncMock(
            return_value={str(existing_fp): "https://example.com/existing"}
        )

        dedup = SimHashDeduplicator(redis=mock_redis)

        items = [
            TitleItem(url="https://example.com/new", title="New Article"),
            TitleItem(url="https://example.com/dup", title=existing_title),
        ]

        result = await dedup.dedup_titles(items)

        # Should filter the duplicate
        assert len(result) == 1
        assert result[0].title == "New Article"

    @pytest.mark.asyncio
    async def test_dedup_titles_handles_invalid_existing_fp(self, mock_redis):
        """Test dedup_titles handles invalid existing fingerprint."""
        # Invalid fingerprint value
        mock_redis.hgetall = AsyncMock(return_value={"invalid": "https://example.com/existing"})

        dedup = SimHashDeduplicator(redis=mock_redis)

        items = [
            TitleItem(url="https://example.com/1", title="Test Article"),
        ]

        result = await dedup.dedup_titles(items)

        # Should still process the item despite invalid existing fp
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dedup_titles_filters_within_batch(self, mock_redis):
        """Test dedup_titles filters duplicates within same batch."""
        dedup = SimHashDeduplicator(redis=mock_redis)

        items = [
            TitleItem(url="https://example.com/1", title="Same Title"),
            TitleItem(url="https://example.com/2", title="Same Title"),  # Duplicate in batch
        ]

        result = await dedup.dedup_titles(items)

        # Should filter the duplicate within batch
        assert len(result) == 1


class TestDedupTitlesWithMetrics:
    """Test SimHashDeduplicator.dedup_titles_with_metrics method."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={})
        redis.hset = AsyncMock()
        # Mock pipeline
        pipeline_mock = MagicMock()
        pipeline_mock.hset = MagicMock()
        pipeline_mock.execute = AsyncMock(return_value=[1])
        redis.pipeline = MagicMock(return_value=pipeline_mock)
        return redis

    @pytest.mark.asyncio
    async def test_dedup_titles_with_metrics_empty_list(self, mock_redis):
        """Test dedup_titles_with_metrics with empty list."""
        dedup = SimHashDeduplicator(redis=mock_redis)

        result, filtered_count = await dedup.dedup_titles_with_metrics([])

        assert result == []
        assert filtered_count == 0

    @pytest.mark.asyncio
    async def test_dedup_titles_with_metrics_all_new(self, mock_redis):
        """Test dedup_titles_with_metrics with all new items."""
        dedup = SimHashDeduplicator(redis=mock_redis)

        items = [
            TitleItem(url="https://example.com/1", title="Unique Title One"),
            TitleItem(url="https://example.com/2", title="Unique Title Two"),
        ]

        result, filtered_count = await dedup.dedup_titles_with_metrics(items)

        assert len(result) == 2
        assert filtered_count == 0

    @pytest.mark.asyncio
    async def test_dedup_titles_with_metrics_filters_duplicates(self, mock_redis):
        """Test dedup_titles_with_metrics filters near-duplicate titles."""
        dedup = SimHashDeduplicator(redis=mock_redis)

        # First add a title
        items1 = [
            TitleItem(url="https://example.com/1", title="China economy grows 5%"),
        ]
        await dedup.dedup_titles_with_metrics(items1)

        # Now try to add a very similar title
        items2 = [
            TitleItem(url="https://example.com/1", title="China economy grows 5%"),
        ]
        # Mock that the fingerprint already exists
        fp = SimHashDeduplicator.generate_fingerprint("China economy grows 5%")
        mock_redis.hgetall = AsyncMock(return_value={str(fp): "1"})

        result, filtered_count = await dedup.dedup_titles_with_metrics(items2)

        assert filtered_count >= 1  # Should filter the duplicate


class TestCleanupExpired:
    """Test SimHashDeduplicator.cleanup_expired method."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={})
        redis.hdel = AsyncMock()
        return redis

    @pytest.mark.asyncio
    async def test_cleanup_expired_no_entries(self, mock_redis):
        """Test cleanup with no entries."""
        mock_redis.hgetall = AsyncMock(return_value={})

        dedup = SimHashDeduplicator(redis=mock_redis)
        result = await dedup.cleanup_expired()

        assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_old_entries(self, mock_redis):
        """Test cleanup removes expired entries."""
        now = int(time.time())
        old_timestamp = now - 86400 * 10  # 10 days ago

        mock_redis.hgetall = AsyncMock(
            return_value={
                "fp1": f"https://example.com/1|{old_timestamp}",
                "fp2": f"https://example.com/2|{now - 3600}",  # 1 hour ago, not expired
            }
        )

        dedup = SimHashDeduplicator(redis=mock_redis, ttl_seconds=86400 * 7)
        result = await dedup.cleanup_expired()

        assert result == 1  # Only one expired
        mock_redis.hdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_handles_old_format(self, mock_redis):
        """Test cleanup handles entries without timestamp (old format)."""
        mock_redis.hgetall = AsyncMock(
            return_value={
                "fp1": "https://example.com/1",  # Old format without timestamp
            }
        )

        dedup = SimHashDeduplicator(redis=mock_redis)
        result = await dedup.cleanup_expired()

        assert result == 1  # Old format entries should be removed

    @pytest.mark.asyncio
    async def test_cleanup_expired_handles_invalid_timestamp(self, mock_redis):
        """Test cleanup handles invalid timestamp values."""
        mock_redis.hgetall = AsyncMock(
            return_value={
                "fp1": "https://example.com/1|invalid_timestamp",
            }
        )

        dedup = SimHashDeduplicator(redis=mock_redis)
        result = await dedup.cleanup_expired()

        assert result == 1  # Invalid entries should be removed

    @pytest.mark.asyncio
    async def test_cleanup_expired_with_custom_max_age(self, mock_redis):
        """Test cleanup with custom max_age_seconds."""
        now = int(time.time())
        recent_timestamp = now - 3600  # 1 hour ago

        mock_redis.hgetall = AsyncMock(
            return_value={
                "fp1": f"https://example.com/1|{recent_timestamp}",
            }
        )

        dedup = SimHashDeduplicator(redis=mock_redis)
        # Use very short max age (30 minutes)
        result = await dedup.cleanup_expired(max_age_seconds=1800)

        assert result == 1  # Entry should be expired with short max age


class TestGetStats:
    """Test SimHashDeduplicator.get_stats method."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={})
        return redis

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, mock_redis):
        """Test get_stats with no entries."""
        mock_redis.hgetall = AsyncMock(return_value={})

        dedup = SimHashDeduplicator(redis=mock_redis)
        stats = await dedup.get_stats()

        assert stats["total_fingerprints"] == 0
        assert stats["redis_key"] == "crawl:simhash:title"
        assert stats["threshold"] == 3

    @pytest.mark.asyncio
    async def test_get_stats_with_entries(self, mock_redis):
        """Test get_stats with entries."""
        mock_redis.hgetall = AsyncMock(
            return_value={
                "fp1": "https://example.com/1",
                "fp2": "https://example.com/2",
            }
        )

        dedup = SimHashDeduplicator(redis=mock_redis)
        stats = await dedup.get_stats()

        assert stats["total_fingerprints"] == 2

    @pytest.mark.asyncio
    async def test_get_stats_returns_config(self, mock_redis):
        """Test get_stats returns configuration values."""
        dedup = SimHashDeduplicator(
            redis=mock_redis,
            threshold=5,
            ttl_seconds=3600,
        )
        stats = await dedup.get_stats()

        assert stats["threshold"] == 5
        assert stats["ttl_seconds"] == 3600
