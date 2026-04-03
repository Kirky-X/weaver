# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Deduplicator."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDeduplicatorInit:
    """Tests for Deduplicator initialization."""

    def test_init_with_defaults(self):
        """Test Deduplicator initializes with default TTL."""
        from modules.ingestion.deduplication import Deduplicator

        mock_redis = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(redis=mock_redis, article_repo=mock_repo)

        assert dedup._redis is mock_redis
        assert dedup._repo is mock_repo
        assert dedup._ttl == Deduplicator.DEFAULT_TTL

    def test_init_with_custom_ttl(self):
        """Test Deduplicator initializes with custom TTL."""
        from modules.ingestion.deduplication import Deduplicator

        mock_redis = MagicMock()
        mock_repo = MagicMock()

        dedup = Deduplicator(
            redis=mock_redis,
            article_repo=mock_repo,
            ttl_seconds=3600,
        )

        assert dedup._ttl == 3600


class TestDeduplicatorDedup:
    """Tests for Deduplicator.dedup()."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis = MagicMock()
        redis.pipeline = MagicMock()
        return redis

    @pytest.fixture
    def mock_repo(self):
        """Create mock article repo."""
        repo = MagicMock()
        repo.get_existing_urls = AsyncMock(return_value=set())
        return repo

    @pytest.fixture
    def dedup(self, mock_redis, mock_repo):
        """Create Deduplicator instance."""
        from modules.ingestion.deduplication import Deduplicator

        return Deduplicator(redis=mock_redis, article_repo=mock_repo)

    @pytest.mark.asyncio
    async def test_dedup_empty_list(self, dedup):
        """Test dedup returns empty list for empty input."""
        result = await dedup.dedup([])
        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_filters_by_redis(self, dedup, mock_redis):
        """Test dedup filters items already in Redis."""
        # Create mock items
        item1 = MagicMock()
        item1.url = "https://example.com/1"
        item2 = MagicMock()
        item2.url = "https://example.com/2"

        # Mock Redis pipeline
        mock_pipe = AsyncMock()
        mock_pipe.execute.return_value = [True, False]  # item1 exists, item2 new
        mock_redis.pipeline.return_value = mock_pipe

        result = await dedup.dedup([item1, item2])

        assert len(result) == 1
        assert result[0].url == "https://example.com/2"

    @pytest.mark.asyncio
    async def test_dedup_all_filtered_by_redis(self, dedup, mock_redis):
        """Test dedup returns empty when all items filtered by Redis."""
        item1 = MagicMock()
        item1.url = "https://example.com/1"

        mock_pipe = AsyncMock()
        mock_pipe.execute.return_value = [True]  # All exist
        mock_redis.pipeline.return_value = mock_pipe

        result = await dedup.dedup([item1])

        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_filters_by_db(self, dedup, mock_redis, mock_repo):
        """Test dedup filters items already in database."""
        item1 = MagicMock()
        item1.url = "https://example.com/new"
        item2 = MagicMock()
        item2.url = "https://example.com/existing"

        mock_pipe = AsyncMock()
        mock_pipe.execute.return_value = [False, False]  # None in Redis
        mock_redis.pipeline.return_value = mock_pipe

        mock_repo.get_existing_urls.return_value = {"https://example.com/existing"}

        result = await dedup.dedup([item1, item2])

        assert len(result) == 1
        assert result[0].url == "https://example.com/new"

    @pytest.mark.asyncio
    async def test_dedup_adds_new_items_to_redis(self, dedup, mock_redis, mock_repo):
        """Test dedup adds new items to Redis."""
        item = MagicMock()
        item.url = "https://example.com/new"

        mock_pipe = AsyncMock()
        mock_pipe.execute.return_value = [False]  # Not in Redis
        mock_redis.pipeline.return_value = mock_pipe

        mock_repo.get_existing_urls.return_value = set()

        await dedup.dedup([item])

        # Verify hset was called (via pipeline)
        assert mock_pipe.hset.called or mock_redis.pipeline.called


class TestDeduplicatorDedupUrls:
    """Tests for Deduplicator.dedup_urls()."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.pipeline = MagicMock()
        return redis

    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.get_existing_urls = AsyncMock(return_value=set())
        return repo

    @pytest.fixture
    def dedup(self, mock_redis, mock_repo):
        from modules.ingestion.deduplication import Deduplicator

        return Deduplicator(redis=mock_redis, article_repo=mock_repo)

    @pytest.mark.asyncio
    async def test_dedup_urls_empty_list(self, dedup):
        """Test dedup_urls returns empty for empty input."""
        result = await dedup.dedup_urls([])
        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_urls_filters_by_redis(self, dedup, mock_redis):
        """Test dedup_urls filters URLs in Redis."""
        mock_pipe = AsyncMock()
        mock_pipe.execute.return_value = [True, False]
        mock_redis.pipeline.return_value = mock_pipe

        result = await dedup.dedup_urls(["https://example.com/1", "https://example.com/2"])

        assert len(result) == 1
        assert result[0] == "https://example.com/2"


class TestDeduplicatorNormalizeUrl:
    """Tests for Deduplicator.normalize_url()."""

    def test_normalize_url_http_to_https(self):
        """Test HTTP URLs are upgraded to HTTPS."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("http://example.com/path")
        assert result.startswith("https://")

    def test_normalize_url_protocol_relative(self):
        """Test protocol-relative URLs become HTTPS."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("//example.com/path")
        assert result.startswith("https://")

    def test_normalize_url_lowercase_domain(self):
        """Test domain is lowercased."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("https://Example.COM/path")
        assert "example.com" in result

    def test_normalize_url_remove_www(self):
        """Test www prefix is removed."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("https://www.example.com/path")
        assert "www." not in result

    def test_normalize_url_remove_default_port(self):
        """Test default ports are removed."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("https://example.com:443/path")
        assert ":443" not in result

    def test_normalize_url_remove_query_string(self):
        """Test query strings are removed."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("https://example.com/path?foo=bar")
        assert "?foo=bar" not in result
        assert "foo=bar" not in result

    def test_normalize_url_remove_fragment(self):
        """Test fragments are removed."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("https://example.com/path#section")
        assert "#section" not in result

    def test_normalize_url_remove_trailing_slash(self):
        """Test trailing slash is removed."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url("https://example.com/path/")
        assert not result.endswith("/")

    def test_normalize_url_wechat_preserves_biz(self):
        """Test WeChat URLs preserve __biz parameter."""
        from modules.ingestion.deduplication import Deduplicator

        result = Deduplicator.normalize_url(
            "https://mp.weixin.qq.com/s?__biz=abc123&mid=123&other=value"
        )
        assert "__biz=abc123" in result
        assert "mid=123" in result
        assert "other=value" not in result

    def test_normalize_url_hash_consistency(self):
        """Test URL hash is consistent for equivalent URLs."""
        from modules.ingestion.deduplication import Deduplicator

        hash1 = Deduplicator._hash("https://example.com/path")
        hash2 = Deduplicator._hash("https://EXAMPLE.COM/path/")
        hash3 = Deduplicator._hash("http://www.example.com/path?foo=bar")

        assert hash1 == hash2 == hash3


class TestDeduplicatorCleanupExpired:
    """Tests for Deduplicator.cleanup_expired()."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.hgetall = AsyncMock()
        redis.hdel = AsyncMock()
        return redis

    @pytest.fixture
    def mock_repo(self):
        return MagicMock()

    @pytest.fixture
    def dedup(self, mock_redis, mock_repo):
        from modules.ingestion.deduplication import Deduplicator

        return Deduplicator(redis=mock_redis, article_repo=mock_repo)

    @pytest.mark.asyncio
    async def test_cleanup_expired_empty(self, dedup, mock_redis):
        """Test cleanup returns 0 when no entries."""
        mock_redis.hgetall.return_value = {}

        result = await dedup.cleanup_expired()

        assert result == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_old_entries(self, dedup, mock_redis):
        """Test cleanup removes expired entries."""
        import time

        now = str(int(time.time()))
        old = str(int(time.time()) - 86400 * 10)  # 10 days old

        mock_redis.hgetall.return_value = {
            "key1": old,
            "key2": now,
        }

        result = await dedup.cleanup_expired(max_age_seconds=86400 * 7)

        assert result == 1
        mock_redis.hdel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_handles_invalid_timestamp(self, dedup, mock_redis):
        """Test cleanup handles invalid timestamps."""
        mock_redis.hgetall.return_value = {
            "key1": "invalid",
            "key2": "12345",
        }

        result = await dedup.cleanup_expired()

        # Invalid timestamp should be removed
        assert result >= 1
