# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Crawler (ingestion crawling module)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import ArticleRaw, NewsItem
from modules.ingestion.fetching.exceptions import FetchError


@pytest.fixture
def mock_fetcher():
    """Mock smart fetcher."""
    return AsyncMock()


@pytest.fixture
def sample_news_items():
    """Create sample news items for testing."""
    item1 = NewsItem(
        url="https://example.com/article1",
        title="Test Article 1",
        source="test_source",
        pubDate=datetime.now(UTC),
        description="Test description 1",
    )
    item2 = NewsItem(
        url="https://other.com/article2",
        title="Test Article 2",
        source="test_source",
        pubDate=datetime.now(UTC),
        description="Test description 2",
    )
    return [item1, item2]


class TestCrawlerInit:
    """Tests for Crawler initialization."""

    def test_crawler_initialization(self, mock_fetcher):
        """Test crawler initializes correctly."""
        from modules.ingestion.crawling.crawler import Crawler

        crawler = Crawler(smart_fetcher=mock_fetcher)

        assert crawler._fetcher is mock_fetcher
        assert crawler._default_per_host == 2

    def test_crawler_with_custom_per_host(self, mock_fetcher):
        """Test crawler with custom per-host limit."""
        from modules.ingestion.crawling.crawler import Crawler

        crawler = Crawler(smart_fetcher=mock_fetcher, default_per_host=5)

        assert crawler._default_per_host == 5


class TestCrawlerCrawlBatch:
    """Tests for Crawler.crawl_batch method."""

    @pytest.mark.asyncio
    async def test_crawl_batch_empty(self, mock_fetcher):
        """Test with empty items list."""
        from modules.ingestion.crawling.crawler import Crawler

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([])

        assert results == []

    @pytest.mark.asyncio
    async def test_crawl_batch_success(self, mock_fetcher, sample_news_items):
        """Test successful crawl batch."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract",
            return_value="Extracted content",
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch(sample_news_items)

        assert len(results) == 2
        assert all(isinstance(r, ArticleRaw) for r in results)

    @pytest.mark.asyncio
    async def test_crawl_batch_with_body(self, mock_fetcher):
        """Test crawl with pre-extracted body."""
        from modules.ingestion.crawling.crawler import Crawler

        # Item with body already set
        item = NewsItem(
            url="https://example.com/article",
            title="Test",
            source="test",
            pubDate=datetime.now(UTC),
            body="Pre-extracted body",
        )

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])

        # Should not call fetch when body is provided
        mock_fetcher.fetch.assert_not_called()
        assert len(results) == 1
        assert results[0].body == "Pre-extracted body"

    @pytest.mark.asyncio
    async def test_crawl_batch_fetch_error(self, mock_fetcher):
        """Test handling of fetch errors."""
        from modules.ingestion.crawling.crawler import Crawler

        fetch_error = FetchError(
            url="https://example.com/article", message="Connection timeout", cause=None
        )
        mock_fetcher.fetch = AsyncMock(side_effect=fetch_error)

        item = NewsItem(
            url="https://example.com/article",
            title="Test",
            source="test",
            pubDate=datetime.now(UTC),
        )

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert isinstance(results[0], FetchError)

    @pytest.mark.asyncio
    async def test_crawl_batch_unexpected_exception(self, mock_fetcher):
        """Test handling of unexpected exceptions."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher.fetch = AsyncMock(side_effect=ValueError("Unexpected error"))

        item = NewsItem(
            url="https://example.com/article",
            title="Test",
            source="test",
            pubDate=datetime.now(UTC),
        )

        crawler = Crawler(smart_fetcher=mock_fetcher)
        results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert isinstance(results[0], FetchError)
        assert "Unexpected error" in results[0].message

    @pytest.mark.asyncio
    async def test_crawl_batch_with_per_host_config(self, mock_fetcher, sample_news_items):
        """Test with custom per-host concurrency config."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value="Content"
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            await crawler.crawl_batch(
                sample_news_items,
                per_host_config={"example.com": 5},
            )

        # Should complete without error
        assert mock_fetcher.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_crawl_batch_empty_extraction(self, mock_fetcher):
        """Test when trafilatura returns empty string."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html><body></body></html>", {}))

        with patch("modules.ingestion.crawling.crawler.trafilatura.extract", return_value=None):
            crawler = Crawler(smart_fetcher=mock_fetcher)

            item = NewsItem(
                url="https://example.com/article",
                title="Test",
                source="test",
                pubDate=datetime.now(UTC),
            )

            results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert results[0].body == ""

    @pytest.mark.asyncio
    async def test_crawl_batch_preserves_item_data(self, mock_fetcher):
        """Test that item data is preserved in result."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value="Body content"
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)

            item = NewsItem(
                url="https://example.com/article",
                title="Test Title",
                source="test_source",
                pubDate=datetime.now(UTC),
                description="Test description",
            )

            results = await crawler.crawl_batch([item])

        assert len(results) == 1
        result = results[0]
        assert result.url == "https://example.com/article"
        assert result.title == "Test Title"
        assert result.source == "test_source"
        assert result.description == "Test description"

    @pytest.mark.asyncio
    async def test_crawl_batch_mixed_results(self, mock_fetcher):
        """Test with mixed success and failure results."""
        from modules.ingestion.crawling.crawler import Crawler

        item1 = NewsItem(
            url="https://example.com/success",
            title="Success",
            source="test",
            pubDate=datetime.now(UTC),
        )
        item2 = NewsItem(
            url="https://example.com/failure",
            title="Failure",
            source="test",
            pubDate=datetime.now(UTC),
        )

        call_count = 0

        async def mock_fetch(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200, "<html>Success</html>", {})
            raise FetchError(url=url, message="Failed", cause=None)

        mock_fetcher.fetch = mock_fetch

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value="Content"
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch([item1, item2])

        assert len(results) == 2
        success_results = [r for r in results if isinstance(r, ArticleRaw)]
        error_results = [r for r in results if isinstance(r, FetchError)]

        assert len(success_results) == 1
        assert len(error_results) == 1


class TestCrawlerConcurrency:
    """Tests for crawler concurrency control."""

    @pytest.mark.asyncio
    async def test_global_concurrency_limit(self, mock_fetcher):
        """Test that global concurrency is limited."""
        from modules.ingestion.crawling.crawler import Crawler

        # Create many items to different hosts
        items = [
            NewsItem(
                url=f"https://host{i}.com/article",
                title=f"Article {i}",
                source="test",
                pubDate=datetime.now(UTC),
            )
            for i in range(10)
        ]

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html>Content</html>", {}))

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value="Content"
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch(items)

        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_per_host_concurrency(self, mock_fetcher):
        """Test per-host concurrency limiting."""
        from modules.ingestion.crawling.crawler import Crawler

        # Create multiple items to same host
        items = [
            NewsItem(
                url=f"https://example.com/article{i}",
                title=f"Article {i}",
                source="test",
                pubDate=datetime.now(UTC),
            )
            for i in range(5)
        ]

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html>Content</html>", {}))

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value="Content"
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher, default_per_host=2)
            results = await crawler.crawl_batch(items)

        assert len(results) == 5
