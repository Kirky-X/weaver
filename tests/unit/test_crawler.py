# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Crawler module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.collector.crawler import GLOBAL_MAX_CONCURRENCY, Crawler
from modules.fetcher.exceptions import FetchError


class TestCrawler:
    """Tests for Crawler."""

    @pytest.fixture
    def mock_fetcher(self):
        """Mock smart fetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))
        return fetcher

    @pytest.fixture
    def mock_news_items(self):
        """Mock news items."""
        items = []
        for i in range(5):
            item = MagicMock()
            item.url = f"https://example{i}.com/article{i}"
            item.title = f"Article {i}"
            item.source = f"source_{i}"
            item.pubDate = datetime.now(UTC)
            yield item
        return items

    def test_initialization(self, mock_fetcher):
        """Test crawler initializes correctly."""
        crawler = Crawler(smart_fetcher=mock_fetcher)
        assert crawler._fetcher is mock_fetcher
        assert crawler._default_per_host == 2

    def test_initialization_custom_per_host(self, mock_fetcher):
        """Test crawler with custom per-host limit."""
        crawler = Crawler(smart_fetcher=mock_fetcher, default_per_host=5)
        assert crawler._default_per_host == 5

    def test_global_max_concurrency(self):
        """Test global max concurrency constant."""
        assert GLOBAL_MAX_CONCURRENCY == 32

    @pytest.mark.asyncio
    async def test_crawl_batch_success(self, mock_fetcher):
        """Test successful batch crawling."""
        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Test Article"
        item.source = "test_source"
        item.pubDate = datetime.now(UTC)

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert not isinstance(results[0], Exception)

    @pytest.mark.asyncio
    async def test_global_concurrency_limit(self, mock_fetcher):
        """Test global concurrency is limited."""
        items = []
        for i in range(100):
            item = MagicMock()
            item.url = f"https://host{i}.com/article"
            item.title = f"Article {i}"
            item.source = "test"
            item.pubDate = None
            items.append(item)

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch(items)

        assert len(results) == 100

    @pytest.mark.asyncio
    async def test_per_host_concurrency(self, mock_fetcher):
        """Test per-host concurrency limit."""
        items = []
        for i in range(10):
            item = MagicMock()
            item.url = f"https://example.com/article{i}"
            item.title = f"Article {i}"
            item.source = "test"
            item.pubDate = None
            items.append(item)

        crawler = Crawler(smart_fetcher=mock_fetcher, default_per_host=2)
        results = await crawler.crawl_batch(items)

        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_per_host_config_override(self, mock_fetcher):
        """Test per-host config override."""
        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Test"
        item.source = "test"
        item.pubDate = None
        item.body = ""

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item], per_host_config={"example.com": 5})

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_return_exceptions(self, mock_fetcher):
        """Test exceptions are returned in results."""
        mock_fetcher.fetch = AsyncMock(side_effect=Exception("Network error"))

        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Test"
        item.source = "test"
        item.pubDate = None
        item.body = ""

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert isinstance(results[0], Exception)

    @pytest.mark.asyncio
    async def test_trafilatura_extraction(self, mock_fetcher):
        """Test trafilatura content extraction."""
        mock_fetcher.fetch = AsyncMock(
            return_value=(200, "<html><body><p>Article content here</p></body></html>", {})
        )

        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Test"
        item.source = "test"
        item.pubDate = None
        item.body = ""

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert not isinstance(results[0], Exception)

    @pytest.mark.asyncio
    async def test_multiple_hosts(self, mock_fetcher):
        """Test crawling from multiple hosts."""
        items = []
        hosts = ["example1.com", "example2.com", "example3.com"]
        for host in hosts:
            item = MagicMock()
            item.url = f"https://{host}/article"
            item.title = "Test"
            item.source = "test"
            item.pubDate = None
            item.body = ""
            items.append(item)

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch(items)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_empty_batch(self, mock_fetcher):
        """Test crawling empty batch."""
        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([])

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_error_wrapping(self, mock_fetcher):
        """Test exceptions are wrapped as FetchError with URL context."""
        original_error = ConnectionError("Connection refused")
        mock_fetcher.fetch = AsyncMock(side_effect=original_error)

        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Test"
        item.source = "test"
        item.pubDate = None
        item.body = ""

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert isinstance(results[0], FetchError)
        assert results[0].url == "https://example.com/article"
        assert "Connection refused" in results[0].message
        assert results[0].cause is original_error

    @pytest.mark.asyncio
    async def test_fetch_error_preserves_all_errors(self, mock_fetcher):
        """Test all errors are preserved in FetchError."""
        mock_fetcher.fetch = AsyncMock(side_effect=ValueError("Invalid URL"))

        items = []
        for i in range(3):
            item = MagicMock()
            item.url = f"https://example{i}.com/article"
            item.title = f"Article {i}"
            item.source = "test"
            item.pubDate = None
            item.body = ""
            items.append(item)

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch(items)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert isinstance(result, FetchError)
            assert result.url == f"https://example{i}.com/article"
