# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SimHash deduplicator module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.deduplication.simhash_dedup import SimHashDeduplicator, TitleItem


class TestSimHashFingerprint:
    """Tests for fingerprint generation."""

    def test_generate_fingerprint_returns_int(self):
        """Fingerprint should be an integer."""
        fp = SimHashDeduplicator.generate_fingerprint("Test Title")
        assert isinstance(fp, int)

    def test_identical_titles_same_fingerprint(self):
        """Identical titles should produce same fingerprint."""
        title = "OpenAI发布GPT-5，性能大幅提升"
        fp1 = SimHashDeduplicator.generate_fingerprint(title)
        fp2 = SimHashDeduplicator.generate_fingerprint(title)
        assert fp1 == fp2

    def test_different_titles_different_fingerprint(self):
        """Different titles should produce different fingerprints."""
        fp1 = SimHashDeduplicator.generate_fingerprint("科技新闻：AI发展迅速")
        fp2 = SimHashDeduplicator.generate_fingerprint("体育新闻：足球比赛结果")
        assert fp1 != fp2

    def test_chinese_title_fingerprint(self):
        """Chinese title should generate valid fingerprint."""
        fp = SimHashDeduplicator.generate_fingerprint("OpenAI发布GPT-5，性能大幅提升")
        assert isinstance(fp, int)
        assert fp > 0  # 64-bit fingerprint

    def test_english_title_fingerprint(self):
        """English title should generate valid fingerprint."""
        fp = SimHashDeduplicator.generate_fingerprint("Apple Announces New iPhone")
        assert isinstance(fp, int)
        assert fp > 0

    def test_empty_title_fingerprint(self):
        """Empty title should still produce a fingerprint."""
        fp = SimHashDeduplicator.generate_fingerprint("")
        assert isinstance(fp, int)


class TestHammingDistance:
    """Tests for Hamming distance calculation."""

    def test_identical_fingerprints_distance_zero(self):
        """Identical fingerprints have distance 0."""
        fp = SimHashDeduplicator.generate_fingerprint("Test Title")
        distance = SimHashDeduplicator.hamming_distance(fp, fp)
        assert distance == 0

    def test_different_fingerprints_positive_distance(self):
        """Different fingerprints have positive distance."""
        fp1 = SimHashDeduplicator.generate_fingerprint("Title A")
        fp2 = SimHashDeduplicator.generate_fingerprint("Title B completely different")
        distance = SimHashDeduplicator.hamming_distance(fp1, fp2)
        assert distance > 0

    def test_similar_titles_low_distance(self):
        """Similar titles should have low Hamming distance."""
        fp1 = SimHashDeduplicator.generate_fingerprint("OpenAI发布GPT-5")
        fp2 = SimHashDeduplicator.generate_fingerprint("OpenAI 发布 GPT-5")  # Added spaces
        distance = SimHashDeduplicator.hamming_distance(fp1, fp2)
        # Similar titles should have distance ≤ 10
        assert distance <= 10

    def test_dissimilar_titles_high_distance(self):
        """Dissimilar titles should have higher distance."""
        fp1 = SimHashDeduplicator.generate_fingerprint("科技新闻：AI发展迅速")
        fp2 = SimHashDeduplicator.generate_fingerprint("体育新闻：足球比赛结果")
        distance = SimHashDeduplicator.hamming_distance(fp1, fp2)
        # Dissimilar titles should have distance > 10
        assert distance > 10


class TestSimHashDeduplicator:
    """Tests for SimHashDeduplicator class."""

    def test_initialization(self):
        """Test deduplicator initializes correctly."""
        mock_cache = MagicMock()
        dedup = SimHashDeduplicator(cache=mock_cache)

        assert dedup._cache is mock_cache
        assert dedup._threshold == 3
        assert dedup.SIMHASH_KEY == "crawl:simhash:title"

    def test_custom_threshold(self):
        """Test custom threshold is applied."""
        mock_cache = MagicMock()
        dedup = SimHashDeduplicator(cache=mock_cache, threshold=5)

        assert dedup._threshold == 5


class TestDedupTitles:
    """Tests for title deduplication."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.hgetall = AsyncMock(return_value={})
        cache.hset = AsyncMock(return_value=1)
        cache.hdel = AsyncMock(return_value=1)
        return cache

    @pytest.fixture
    def dedup(self, mock_cache):
        """Create deduplicator with mock Redis."""
        return SimHashDeduplicator(cache=mock_cache)

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self, dedup):
        """Empty input returns empty output."""
        result = await dedup.dedup_titles([])
        assert result == []

    @pytest.mark.asyncio
    async def test_single_item_passes(self, dedup, mock_cache):
        """Single unique item passes through."""
        items = [TitleItem(url="https://example.com/1", title="Unique Title")]
        result = await dedup.dedup_titles(items)

        assert len(result) == 1
        assert result[0].url == "https://example.com/1"

    @pytest.mark.asyncio
    async def test_identical_titles_filtered(self, dedup, mock_cache):
        """Identical titles are filtered out."""
        items = [
            TitleItem(url="https://example.com/1", title="Same Title"),
            TitleItem(url="https://example.com/2", title="Same Title"),
        ]
        result = await dedup.dedup_titles(items)

        # Only first should pass
        assert len(result) == 1
        assert result[0].url == "https://example.com/1"

    @pytest.mark.asyncio
    async def test_similar_titles_filtered(self, dedup, mock_cache):
        """Similar titles (within threshold) are filtered."""
        # These titles are very similar
        items = [
            TitleItem(url="https://example.com/1", title="OpenAI发布GPT-5"),
            TitleItem(url="https://example.com/2", title="OpenAI 发布 GPT-5"),  # Added spaces
        ]
        result = await dedup.dedup_titles(items)

        # Should be filtered as duplicates
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dissimilar_titles_both_pass(self, dedup, mock_cache):
        """Dissimilar titles both pass through."""
        items = [
            TitleItem(url="https://example.com/1", title="科技新闻：AI发展迅速"),
            TitleItem(url="https://example.com/2", title="体育新闻：足球比赛结果"),
        ]
        result = await dedup.dedup_titles(items)

        # Both should pass
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_existing_fingerprints_checked(self, dedup, mock_cache):
        """Existing fingerprints in Redis are checked."""
        # Simulate existing fingerprint
        existing_fp = SimHashDeduplicator.generate_fingerprint("Existing Title")
        mock_cache.hgetall = AsyncMock(
            return_value={str(existing_fp): "https://existing.com/1|1234567890"}
        )

        items = [
            TitleItem(url="https://example.com/1", title="Existing Title"),
        ]
        result = await dedup.dedup_titles(items)

        # Should be filtered as duplicate
        assert len(result) == 0


class TestDedupTitlesWithMetrics:
    """Tests for dedup_titles_with_metrics."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.hgetall = AsyncMock(return_value={})
        cache.hset = AsyncMock(return_value=1)
        cache.hdel = AsyncMock(return_value=1)
        return cache

    @pytest.fixture
    def dedup(self, mock_cache):
        """Create deduplicator with mock Redis."""
        return SimHashDeduplicator(cache=mock_cache)

    @pytest.mark.asyncio
    async def test_returns_filtered_count(self, dedup, mock_cache):
        """Returns tuple of (unique_items, filtered_count)."""
        items = [
            TitleItem(url="https://example.com/1", title="Same Title"),
            TitleItem(url="https://example.com/2", title="Same Title"),
            TitleItem(url="https://example.com/3", title="Different Title"),
        ]
        unique, filtered = await dedup.dedup_titles_with_metrics(items)

        # Two duplicates, one unique
        assert len(unique) == 2
        assert filtered == 1


class TestSimHashStats:
    """Tests for get_stats method."""

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test get_stats returns correct structure."""
        mock_cache = MagicMock()
        mock_cache.hgetall = AsyncMock(return_value={"123": "url1|100", "456": "url2|200"})
        dedup = SimHashDeduplicator(cache=mock_cache, threshold=5)

        stats = await dedup.get_stats()

        assert stats["total_fingerprints"] == 2
        assert stats["redis_key"] == "crawl:simhash:title"
        assert stats["threshold"] == 5
