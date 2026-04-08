# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Deduplicator (ingestion module)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.deduplication.deduplicator import Deduplicator


class TestDeduplicatorInit:
    """Tests for Deduplicator initialization."""

    def test_deduplicator_initialization(self):
        """Test deduplicator initializes correctly."""
        mock_cache = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        assert dedup._cache is mock_cache
        assert dedup._repo is mock_repo
        assert dedup.DEDUP_KEY == "crawl:dedup"

    def test_deduplicator_with_custom_ttl(self):
        """Test deduplicator with custom TTL."""
        mock_cache = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo, ttl_seconds=3600)

        assert dedup._ttl == 3600

    def test_default_ttl(self):
        """Test default TTL is 7 days."""
        mock_cache = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        assert dedup._ttl == Deduplicator.DEFAULT_TTL  # 7 days (604800 seconds)


class TestDeduplicatorDedup:
    """Tests for Deduplicator.dedup method."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.ping = AsyncMock(return_value=True)
        cache.hexists_many = AsyncMock(return_value=[False, False])
        cache.hset = AsyncMock(return_value=1)
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
    async def test_dedup_with_no_items(self):
        """Test deduplication with empty list."""
        mock_cache = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup([])

        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_all_new_items(self, mock_cache, mock_repo, mock_items):
        """Test deduplication with all new items."""
        mock_repo.get_existing_urls = AsyncMock(return_value=[])
        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup(mock_items)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_dedup_filters_redis_duplicates(self, mock_cache, mock_repo):
        """Test Redis first-level deduplication filters existing URLs."""
        # First URL exists in Redis, second is new
        mock_cache.hexists_many = AsyncMock(return_value=[True, False])

        item1 = MagicMock()
        item1.url = "https://example.com/existing"
        item2 = MagicMock()
        item2.url = "https://example.com/new"

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)
        mock_repo.get_existing_urls = AsyncMock(return_value=[])

        result = await dedup.dedup([item1, item2])

        assert len(result) == 1
        assert result[0].url == "https://example.com/new"

    @pytest.mark.asyncio
    async def test_dedup_filters_db_duplicates(self, mock_cache, mock_repo):
        """Test DB second-level deduplication."""
        mock_cache.hexists_many = AsyncMock(return_value=[False, False])

        item1 = MagicMock()
        item1.url = "https://example.com/existing"
        item2 = MagicMock()
        item2.url = "https://example.com/new"

        mock_repo.get_existing_urls = AsyncMock(return_value=["https://example.com/existing"])

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup([item1, item2])

        assert len(result) == 1
        assert result[0].url == "https://example.com/new"

    @pytest.mark.asyncio
    async def test_dedup_all_filtered(self, mock_cache, mock_repo):
        """Test all items filtered out."""
        mock_cache.hexists_many = AsyncMock(return_value=[True, True])

        item1 = MagicMock()
        item1.url = "https://example.com/article1"
        item2 = MagicMock()
        item2.url = "https://example.com/article2"

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup([item1, item2])

        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_without_repo_get_existing_urls(self, mock_cache):
        """Test dedup when repo doesn't have get_existing_urls method."""
        mock_cache.hexists_many = AsyncMock(return_value=[False])

        mock_repo = MagicMock(spec=[])  # No get_existing_urls method

        item = MagicMock()
        item.url = "https://example.com/article"

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup([item])

        assert len(result) == 1


class TestDeduplicatorDedupUrls:
    """Tests for Deduplicator.dedup_urls method."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        cache.hexists_many = AsyncMock(return_value=[False, False])
        cache.hset = AsyncMock(return_value=1)
        return cache

    @pytest.fixture
    def mock_repo(self):
        """Mock article repository."""
        repo = MagicMock()
        repo.get_existing_urls = AsyncMock(return_value=[])
        return repo

    @pytest.mark.asyncio
    async def test_dedup_urls_empty_list(self, mock_cache, mock_repo):
        """Test dedup_urls with empty list."""
        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup_urls([])

        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_urls_all_new(self, mock_cache, mock_repo):
        """Test dedup_urls with all new URLs."""
        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup_urls(["https://example.com/1", "https://example.com/2"])

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_dedup_urls_filters_redis_duplicates(self, mock_cache, mock_repo):
        """Test dedup_urls filters Redis duplicates."""
        mock_cache.hexists_many = AsyncMock(return_value=[True, False])

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.dedup_urls(["https://example.com/existing", "https://example.com/new"])

        assert len(result) == 1
        assert result[0] == "https://example.com/new"


class TestDeduplicatorCleanupExpired:
    """Tests for Deduplicator.cleanup_expired method."""

    @pytest.fixture
    def mock_cache(self):
        """Mock Redis client."""
        cache = MagicMock()
        return cache

    @pytest.fixture
    def mock_repo(self):
        """Mock article repository."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_cleanup_expired_no_entries(self, mock_cache, mock_repo):
        """Test cleanup with no entries."""
        mock_cache.hgetall = AsyncMock(return_value={})

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.cleanup_expired()

        assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_with_old_entries(self, mock_cache, mock_repo):
        """Test cleanup removes old entries."""
        import time

        old_timestamp = str(int(time.time()) - 86400 * 10)  # 10 days ago
        new_timestamp = str(int(time.time()) - 3600)  # 1 hour ago

        mock_cache.hgetall = AsyncMock(
            return_value={
                "old_key1": old_timestamp,
                "old_key2": old_timestamp,
                "new_key": new_timestamp,
            }
        )
        mock_cache.hdel = AsyncMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo, ttl_seconds=86400 * 7)

        result = await dedup.cleanup_expired()

        assert result == 2
        mock_cache.hdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_with_invalid_timestamp(self, mock_cache, mock_repo):
        """Test cleanup handles invalid timestamps."""
        mock_cache.hgetall = AsyncMock(
            return_value={
                "invalid_key": "not_a_number",
            }
        )
        mock_cache.hdel = AsyncMock()

        dedup = Deduplicator(cache=mock_cache, article_repo=mock_repo)

        result = await dedup.cleanup_expired()

        assert result == 1


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
        """Clean URL without www or query string is unchanged."""
        result = Deduplicator.normalize_url("https://36kr.com/p/123")
        assert result == "https://36kr.com/p/123"

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
        """Relative path segments should be resolved."""
        result = Deduplicator.normalize_url("https://example.com/a/../b/./c")
        assert result == "https://example.com/b/c"

    def test_removes_root_trailing_slash(self):
        """Trailing slash on root path should be removed."""
        result = Deduplicator.normalize_url("https://example.com/")
        assert result == "https://example.com"

    def test_wechat_url_preserves_biz_mid(self):
        """WeChat URLs should preserve __biz and mid params."""
        result = Deduplicator.normalize_url(
            "https://mp.weixin.qq.com/s?__biz=MjM5NzQ5MTkyMA==&mid=2658216812&idx=1"
        )
        assert "__biz=MjM5NzQ5MTkyMA" in result
        assert "mid=2658216812" in result
        assert "idx=1" not in result  # Other params should be removed

    def test_empty_url(self):
        """Empty URL should be handled gracefully."""
        result = Deduplicator.normalize_url("")
        assert isinstance(result, str)


class TestHashFunction:
    """Tests for Deduplicator._hash method."""

    def test_hash_consistency(self):
        """Same URL produces same hash."""
        url = "https://example.com/article"
        hash1 = Deduplicator._hash(url)
        hash2 = Deduplicator._hash(url)

        assert hash1 == hash2
        assert len(hash1) == 16  # sha256[:16]

    def test_hash_different_urls(self):
        """Different URLs produce different hashes."""
        hash1 = Deduplicator._hash("https://example.com/article1")
        hash2 = Deduplicator._hash("https://example.com/article2")

        assert hash1 != hash2

    def test_hash_http_and_https_produce_same_hash(self):
        """http and https variants produce identical hashes."""
        h1 = Deduplicator._hash("http://example.com/article/123")
        h2 = Deduplicator._hash("https://example.com/article/123")
        assert h1 == h2

    def test_hash_www_and_non_www_produce_same_hash(self):
        """www and non-www variants produce identical hashes."""
        h1 = Deduplicator._hash("https://www.36kr.com/p/123")
        h2 = Deduplicator._hash("https://36kr.com/p/123")
        assert h1 == h2

    def test_hash_query_params_stripped(self):
        """Query params do not affect the hash."""
        h1 = Deduplicator._hash("https://36kr.com/p/123")
        h2 = Deduplicator._hash("https://36kr.com/p/123?f=rss")
        assert h1 == h2
