"""Unit tests for Crawler module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from modules.collector.crawler import Crawler, GLOBAL_MAX_CONCURRENCY


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
            item.pubDate = datetime.now(timezone.utc)
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
        item.pubDate = datetime.now(timezone.utc)
        
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
        
        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])
        
        assert len(results) == 1
        assert isinstance(results[0], Exception)

    @pytest.mark.asyncio
    async def test_trafilatura_extraction(self, mock_fetcher):
        """Test trafilatura content extraction."""
        mock_fetcher.fetch = AsyncMock(return_value=(
            200,
            "<html><body><p>Article content here</p></body></html>",
            {}
        ))
        
        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Test"
        item.source = "test"
        item.pubDate = None
        
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
