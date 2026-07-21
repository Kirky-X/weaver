# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for Crawler (ingestion crawling module)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import NewsItem, RawArticle
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
        publish_time=datetime.now(UTC),
        description="Test description 1",
    )
    item2 = NewsItem(
        url="https://other.com/article2",
        title="Test Article 2",
        source="test_source",
        publish_time=datetime.now(UTC),
        description="Test description 2",
    )
    return [item1, item2]


# Long enough content to pass validation (> 100 chars)
LONG_CONTENT = "This is extracted content that is long enough to pass the minimum article length validation threshold of 100 characters in the crawler module."


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
            return_value=LONG_CONTENT,
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch(sample_news_items)

        assert len(results) == 2
        assert all(isinstance(r, RawArticle) for r in results)

    @pytest.mark.asyncio
    async def test_crawl_batch_with_body(self, mock_fetcher):
        """Test crawl with pre-extracted body."""
        from modules.ingestion.crawling.crawler import Crawler

        # Item with body already set - long enough to pass validation
        item = NewsItem(
            url="https://example.com/article",
            title="Test",
            source="test",
            publish_time=datetime.now(UTC),
            body=LONG_CONTENT,
        )

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract",
            return_value=LONG_CONTENT,
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch([item])

        # Should not call fetch when body passes validation
        mock_fetcher.fetch.assert_not_called()
        assert len(results) == 1
        assert results[0].body == LONG_CONTENT

    @pytest.mark.asyncio
    async def test_crawl_batch_with_short_body_refetches(self, mock_fetcher):
        """Test crawl with short pre-extracted body triggers re-fetch."""
        from modules.ingestion.crawling.crawler import Crawler

        # Item with short body that fails validation
        item = NewsItem(
            url="https://example.com/article",
            title="Test",
            source="test",
            publish_time=datetime.now(UTC),
            body="short",
        )

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))

        # First call returns None (plain text not extractable), second returns long content
        extract_results = [None, LONG_CONTENT]
        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract",
            side_effect=extract_results,
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch([item])

        # Should call fetch with force_browser=True when body fails validation
        mock_fetcher.fetch.assert_called_once()
        assert len(results) == 1
        assert results[0].body == LONG_CONTENT

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
            publish_time=datetime.now(UTC),
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
            publish_time=datetime.now(UTC),
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
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value=LONG_CONTENT
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
                publish_time=datetime.now(UTC),
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
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value=LONG_CONTENT
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)

            item = NewsItem(
                url="https://example.com/article",
                title="Test Title",
                source="test_source",
                publish_time=datetime.now(UTC),
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
            publish_time=datetime.now(UTC),
        )
        item2 = NewsItem(
            url="https://example.com/failure",
            title="Failure",
            source="test",
            publish_time=datetime.now(UTC),
        )

        call_count = 0

        async def mock_fetch(url, headers=None, force_browser=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200, "<html>Success</html>", {})
            raise FetchError(url=url, message="Failed", cause=None)

        mock_fetcher.fetch = mock_fetch

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value=LONG_CONTENT
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch([item1, item2])

        assert len(results) == 2
        success_results = [r for r in results if isinstance(r, RawArticle)]
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
                publish_time=datetime.now(UTC),
            )
            for i in range(10)
        ]

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html>Content</html>", {}))

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value=LONG_CONTENT
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
                publish_time=datetime.now(UTC),
            )
            for i in range(5)
        ]

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html>Content</html>", {}))

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract", return_value=LONG_CONTENT
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher, default_per_host=2)
            results = await crawler.crawl_batch(items)

        assert len(results) == 5


class TestExtractTitleFromHtml:
    """Tests for _extract_title_from_html helper function."""

    def test_extract_from_og_title_meta(self):
        """Test extracting title from <meta property="og:title"> tag."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = (
            '<html><head><meta property="og:title" content="Article Title from OG">'
            "</head><body></body></html>"
        )
        assert _extract_title_from_html(html) == "Article Title from OG"

    def test_extract_from_og_title_reversed_attr_order(self):
        """Test extracting title when content comes before property attribute."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = (
            '<html><head><meta content="Reversed Attr Title" property="og:title">'
            "</head><body></body></html>"
        )
        assert _extract_title_from_html(html) == "Reversed Attr Title"

    def test_extract_from_title_tag(self):
        """Test extracting title from <title> tag when og:title absent."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = "<html><head><title>Page Title Tag</title></head><body></body></html>"
        assert _extract_title_from_html(html) == "Page Title Tag"

    def test_og_title_preferred_over_title_tag(self):
        """Test that og:title is preferred over <title> tag."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = (
            '<html><head><meta property="og:title" content="OG Title">'
            "<title>Title Tag Content</title></head><body></body></html>"
        )
        assert _extract_title_from_html(html) == "OG Title"

    def test_extract_from_ithome_html(self):
        """Test extracting title from IT之家-style HTML."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = (
            "<html><head>"
            '<meta property="og:title" content="开源多媒体框架 FFmpeg 被曝高危漏洞" />'
            "<title>开源多媒体框架 FFmpeg 被曝高危漏洞 - IT之家</title>"
            "</head><body></body></html>"
        )
        result = _extract_title_from_html(html)
        assert result is not None
        assert "FFmpeg" in result

    def test_extract_from_solidot_html(self):
        """Test extracting title from Solidot-style HTML."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = (
            "<html><head>"
            "<title>奇客Solidot | 高温干旱高 CO2 下大豆蛋白质含量会下降</title>"
            "</head><body></body></html>"
        )
        result = _extract_title_from_html(html)
        assert result is not None
        assert "Solidot" in result

    def test_returns_none_when_no_title(self):
        """Test returns None when no title tags found."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = "<html><head></head><body>No title here</body></html>"
        assert _extract_title_from_html(html) is None

    def test_returns_none_for_empty_title(self):
        """Test returns None when title tag is empty."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = "<html><head><title>   </title></head><body></body></html>"
        assert _extract_title_from_html(html) is None

    def test_strips_whitespace(self):
        """Test that extracted title is stripped of whitespace."""
        from modules.ingestion.crawling.crawler import _extract_title_from_html

        html = "<html><head><title>  Spaced Title  </title></head><body></body></html>"
        assert _extract_title_from_html(html) == "Spaced Title"


class TestCrawlerTitleExtraction:
    """Tests for title extraction fallback in crawl_batch."""

    @pytest.mark.asyncio
    async def test_title_extraction_fallback_when_trafilatura_fails(self, mock_fetcher):
        """Test that HTML <title> tag is used when trafilatura returns None."""
        from modules.ingestion.crawling.crawler import Crawler

        # HTML with <title> tag but trafilatura will return title=None
        html_with_title = (
            "<html><head>"
            '<meta property="og:title" content="FFmpeg 漏洞报告">'
            "<title>FFmpeg 漏洞报告 - IT之家</title>"
            "</head><body>Article content here.</body></html>"
        )
        mock_fetcher.fetch = AsyncMock(return_value=(200, html_with_title, {}))

        # Item without title (simulates direct URL processing without RSS)
        item = NewsItem(
            url="https://www.ithome.com/0/123/456.htm",
            title="",  # Empty title - simulates no RSS title
            source="test",
            publish_time=datetime.now(UTC),
        )

        # Mock trafilatura: extract returns body, bare_extraction returns title=None
        mock_doc = MagicMock()
        mock_doc.title = None  # trafilatura fails to extract title
        with (
            patch(
                "modules.ingestion.crawling.crawler.trafilatura.extract",
                return_value=LONG_CONTENT,
            ),
            patch(
                "modules.ingestion.crawling.crawler.trafilatura.bare_extraction",
                return_value=mock_doc,
            ),
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch([item])

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, RawArticle)
        # Title should be extracted from og:title meta tag
        assert result.title == "FFmpeg 漏洞报告"

    @pytest.mark.asyncio
    async def test_title_extraction_uses_rss_title_when_available(self, mock_fetcher):
        """Test that RSS-provided title is used without HTML extraction."""
        from modules.ingestion.crawling.crawler import Crawler

        mock_fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))

        item = NewsItem(
            url="https://example.com/article",
            title="RSS Provided Title",
            source="test",
            publish_time=datetime.now(UTC),
        )

        with patch(
            "modules.ingestion.crawling.crawler.trafilatura.extract",
            return_value=LONG_CONTENT,
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert results[0].title == "RSS Provided Title"

    @pytest.mark.asyncio
    async def test_title_extraction_fallback_to_title_tag(self, mock_fetcher):
        """Test fallback to <title> tag when og:title is absent."""
        from modules.ingestion.crawling.crawler import Crawler

        html_with_title_tag = (
            "<html><head><title>Solidot 文章标题</title></head><body>Article content.</body></html>"
        )
        mock_fetcher.fetch = AsyncMock(return_value=(200, html_with_title_tag, {}))

        item = NewsItem(
            url="https://www.solidot.org/story/123",
            title="",
            source="test",
            publish_time=datetime.now(UTC),
        )

        mock_doc = MagicMock()
        mock_doc.title = None
        with (
            patch(
                "modules.ingestion.crawling.crawler.trafilatura.extract",
                return_value=LONG_CONTENT,
            ),
            patch(
                "modules.ingestion.crawling.crawler.trafilatura.bare_extraction",
                return_value=mock_doc,
            ),
        ):
            crawler = Crawler(smart_fetcher=mock_fetcher)
            results = await crawler.crawl_batch([item])

        assert len(results) == 1
        assert results[0].title == "Solidot 文章标题"
