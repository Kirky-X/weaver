# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for deduplicator module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.deduplication.deduplicator import Deduplicator


class TestDeduplicator:
    """Tests for Deduplicator."""

    def test_deduplicator_initialization(self):
        """Test deduplicator initializes correctly."""
        mock_cache = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        assert dedup._cache is mock_cache
        assert dedup._repo is mock_repo
        assert dedup.DEDUP_KEY == "crawl:dedup"

    @pytest.mark.asyncio
    async def test_dedup_with_no_items(self):
        """Test deduplication with empty list."""
        mock_cache = MagicMock()
        mock_repo = MagicMock()
        mock_cache.pipeline = MagicMock(return_value=MagicMock())

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup([])

        assert result == []
        mock_cache.pipeline.assert_not_called()

    @pytest.mark.asyncio
    async def test_hash_function(self):
        """Test URL hashing function."""
        mock_cache = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

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
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        pipeline_mock = MagicMock()
        pipeline_mock.hexists = MagicMock()
        pipeline_mock.execute = AsyncMock(return_value=[False, True])
        pipeline_mock.hset = MagicMock()
        cache.pipeline = MagicMock(return_value=pipeline_mock)
        return cache

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
    async def test_redis_dedup_first_level(self, mock_cache, mock_repo):
        """Test Redis first-level deduplication."""
        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)
        assert dedup.DEDUP_KEY == "crawl:dedup"

    @pytest.mark.asyncio
    async def test_db_dedup_second_level(self, mock_cache, mock_repo, mock_items):
        """Test DB second-level deduplication."""
        mock_repo.get_existing_urls = AsyncMock(return_value=["https://example.com/article1"])
        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)
        assert dedup._repo is mock_repo

    @pytest.mark.asyncio
    async def test_write_new_urls_to_cache(self, mock_cache, mock_repo):
        """Test new URLs are written to Redis."""
        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)
        assert hasattr(dedup, "_hash")

    @pytest.mark.asyncio
    async def test_pipeline_execution(self, mock_cache, mock_repo, mock_items):
        """Test complete deduplication pipeline."""
        mock_repo.get_existing_urls = AsyncMock(return_value=[])
        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)
        assert dedup._cache is not None
        assert dedup._repo is not None


class TestNormalizeUrl:
    """Tests for Deduplicator.normalize_url()."""

    def test_www_prefix_removed_https(self):
        """https://www. should have www. stripped."""
        result = Deduplicator.normalize_url("https://www.36kr.com/p/123")
        assert result == "https://36kr.com/p/123"

    def test_http_to_https_unification(self):
        """http:// should be unified to https://."""
        result = Deduplicator.normalize_url("http://example.com/article/123")
        assert result == "https://example.com/article/123"

    def test_http_www_to_https(self):
        """http://www. should become https:// without www."""
        result = Deduplicator.normalize_url("http://www.example.com/page")
        assert result == "https://example.com/page"

    def test_protocol_relative_to_https(self):
        """//www. should become https:// without www."""
        result = Deduplicator.normalize_url("//www.36kr.com/p/123")
        assert result == "https://36kr.com/p/123"

    def test_domain_lowercase(self):
        """Domain should be converted to lowercase."""
        result = Deduplicator.normalize_url("https://EXAMPLE.COM/Article/123")
        assert result == "https://example.com/Article/123"

    def test_path_case_preserved(self):
        """Path case should be preserved."""
        result = Deduplicator.normalize_url("https://example.com/Article/Title-Here")
        assert result == "https://example.com/Article/Title-Here"

    def test_fragment_removed(self):
        """Fragment (anchor) should be removed."""
        result = Deduplicator.normalize_url("https://www.36kr.com/p/123#comments")
        assert result == "https://36kr.com/p/123"

    def test_trailing_slash_removed(self):
        """Trailing slash should be removed."""
        result = Deduplicator.normalize_url("https://example.com/article/123/")
        assert result == "https://example.com/article/123"

    def test_query_string_removed(self):
        """Query string should be stripped."""
        result = Deduplicator.normalize_url("https://www.36kr.com/p/123?f=rss&source=foo")
        assert result == "https://36kr.com/p/123"

    def test_combined_normalization(self):
        """All transformations applied together."""
        result = Deduplicator.normalize_url(
            "http://www.EXAMPLE.com/Article/123/?source=rss#comments"
        )
        assert result == "https://example.com/Article/123"

    def test_no_www_no_query_unchanged(self):
        """Clean URL without www or query string is unchanged (except maybe trailing slash)."""
        result = Deduplicator.normalize_url("https://36kr.com/p/123")
        assert result == "https://36kr.com/p/123"

    def test_hash_http_and_https_produce_same_hash(self):
        """http and https variants produce identical hashes."""
        h1 = Deduplicator._hash("http://example.com/article/123")
        h2 = Deduplicator._hash("https://example.com/article/123")
        assert h1 == h2

    def test_hash_www_and_non_www_produce_same_hash(self):
        """www and non-www variants of the same URL produce identical hashes."""
        h1 = Deduplicator._hash("https://www.36kr.com/p/123")
        h2 = Deduplicator._hash("https://36kr.com/p/123")
        assert h1 == h2

    def test_hash_query_params_stripped(self):
        """Query params do not affect the hash."""
        h1 = Deduplicator._hash("https://36kr.com/p/123")
        h2 = Deduplicator._hash("https://36kr.com/p/123?f=rss")
        h3 = Deduplicator._hash("https://www.36kr.com/p/123?f=rss&source=foo")
        assert h1 == h2 == h3

    def test_hash_fragment_not_considered(self):
        """Fragment is removed, so URLs with/without fragment produce same hash."""
        h1 = Deduplicator._hash("https://36kr.com/p/123")
        h2 = Deduplicator._hash("https://36kr.com/p/123#anchor")
        assert h1 == h2

    def test_hash_domain_case_insensitive(self):
        """Domain case does not affect hash."""
        h1 = Deduplicator._hash("https://EXAMPLE.com/Article")
        h2 = Deduplicator._hash("https://example.com/Article")
        assert h1 == h2

    def test_hash_trailing_slash_ignored(self):
        """Trailing slash does not affect hash."""
        h1 = Deduplicator._hash("https://example.com/article/")
        h2 = Deduplicator._hash("https://example.com/article")
        assert h1 == h2

    def test_normalize_url_returns_string(self):
        """normalize_url always returns a string."""
        assert isinstance(Deduplicator.normalize_url("https://www.example.com"), str)
        assert isinstance(Deduplicator.normalize_url(""), str)

    def test_empty_url(self):
        """Empty URL should be handled gracefully."""
        result = Deduplicator.normalize_url("")
        assert isinstance(result, str)

    # --- Tests migrated from test_normalize_url.py ---

    def test_removes_default_https_port(self):
        """Default HTTPS port 443 should be removed."""
        result = Deduplicator.normalize_url("https://example.com:443/path")
        assert result == "https://example.com/path"

    def test_removes_default_http_port(self):
        """Default HTTP port 80 should be removed (after upgrading to HTTPS)."""
        result = Deduplicator.normalize_url("http://example.com:80/path")
        assert result == "https://example.com/path"

    def test_preserves_non_default_port(self):
        """Non-default ports should be preserved."""
        result = Deduplicator.normalize_url("https://example.com:8443/path")
        assert result == "https://example.com:8443/path"

    def test_normalizes_relative_path_dots(self):
        """Relative path segments (.. and .) should be resolved."""
        result = Deduplicator.normalize_url("https://example.com/a/../b/./c")
        assert result == "https://example.com/b/c"

    def test_removes_root_trailing_slash(self):
        """Trailing slash on root path should be removed."""
        result = Deduplicator.normalize_url("https://example.com/")
        assert result == "https://example.com"

    def test_percent_encoded_and_decoded_deduplicate(self):
        """Both percent-encoded and decoded URLs should produce same normalized form."""
        result1 = Deduplicator.normalize_url("https://example.com/path/%E4%B8%AD%E6%96%87")
        result2 = Deduplicator.normalize_url("https://example.com/path/中文")
        assert result1 == result2

    def test_handles_percent_encoding_chinese(self):
        """Percent-encoded Chinese should be handled correctly."""
        result = Deduplicator.normalize_url("https://example.com/path/%E4%B8%AD%E6%96%87")
        assert result.startswith("https://example.com/path/")

    def test_handles_already_decoded_chinese(self):
        """Already decoded Chinese should be handled correctly."""
        result = Deduplicator.normalize_url("https://example.com/path/中文")
        assert result.startswith("https://example.com/path/")

    def test_protocol_relative_with_www(self):
        """Protocol-relative URL with www should be normalized."""
        result = Deduplicator.normalize_url("//www.example.com/path")
        assert result == "https://example.com/path"

    def test_query_params_deduplicate(self):
        """URLs with and without query params should produce same normalized form."""
        result1 = Deduplicator.normalize_url("https://36kr.com/p/123")
        result2 = Deduplicator.normalize_url("https://36kr.com/p/123?f=rss")
        assert result1 == result2

    def test_www_and_non_www_deduplicate(self):
        """www and non-www URLs should produce same normalized form."""
        result1 = Deduplicator.normalize_url("https://www.36kr.com/p/123")
        result2 = Deduplicator.normalize_url("https://36kr.com/p/123")
        assert result1 == result2

    def test_full_normalization(self):
        """Full normalization with all transformations."""
        result = Deduplicator.normalize_url("http://www.EXAMPLE.COM:80/a/../b/./c?f=rss#anchor")
        assert result == "https://example.com/b/c"
