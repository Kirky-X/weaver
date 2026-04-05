# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Crawl4AIFetcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher


class TestCrawl4AIFetcherInit:
    """Test Crawl4AIFetcher initialization."""

    def test_init_defaults(self):
        """Test initialization with default values."""
        fetcher = Crawl4AIFetcher()

        assert fetcher._headless is True
        assert fetcher._stealth_enabled is True
        assert fetcher._user_agent is None
        assert fetcher._timeout == 30.0
        assert fetcher._initialized is False

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        fetcher = Crawl4AIFetcher(
            headless=False,
            stealth_enabled=False,
            user_agent="CustomAgent/1.0",
            timeout=60.0,
        )

        assert fetcher._headless is False
        assert fetcher._stealth_enabled is False
        assert fetcher._user_agent == "CustomAgent/1.0"
        assert fetcher._timeout == 60.0


class TestCrawl4AIFetcherFetch:
    """Test Crawl4AIFetcher.fetch method."""

    @pytest.fixture
    def mock_crawl_result(self):
        """Create mock CrawlResult."""
        result = MagicMock()
        result.success = True
        result.status_code = 200
        result.html = "<html><body>Test content</body></html>"
        result.response_headers = {"content-type": "text/html"}
        result.error_message = None
        return result

    @pytest.mark.asyncio
    async def test_fetch_success(self, mock_crawl_result):
        """Test successful fetch."""
        fetcher = Crawl4AIFetcher()

        with patch.object(fetcher, "_ensure_initialized", new_callable=AsyncMock):
            fetcher._crawler = MagicMock()
            fetcher._crawler.arun = AsyncMock(return_value=mock_crawl_result)
            fetcher._initialized = True

            status, html, headers = await fetcher.fetch("https://example.com")

            assert status == 200
            assert html == "<html><body>Test content</body></html>"
            assert headers == {"content-type": "text/html"}

    @pytest.mark.asyncio
    async def test_fetch_failure_raises_exception(self):
        """Test failed fetch raises exception."""
        fetcher = Crawl4AIFetcher()

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "Connection timeout"

        with patch.object(fetcher, "_ensure_initialized", new_callable=AsyncMock):
            fetcher._crawler = MagicMock()
            fetcher._crawler.arun = AsyncMock(return_value=mock_result)
            fetcher._initialized = True

            with pytest.raises(RuntimeError, match="Crawl failed"):
                await fetcher.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_without_crawler_raises_error(self):
        """Test fetch without initialized crawler raises error."""
        fetcher = Crawl4AIFetcher()

        with patch.object(fetcher, "_ensure_initialized", new_callable=AsyncMock):
            fetcher._initialized = True
            fetcher._crawler = None

            with pytest.raises(RuntimeError, match="Crawler not initialized"):
                await fetcher.fetch("https://example.com")


class TestCrawl4AIFetcherClose:
    """Test Crawl4AIFetcher.close method."""

    @pytest.mark.asyncio
    async def test_close_with_initialized_crawler(self):
        """Test close with initialized crawler."""
        fetcher = Crawl4AIFetcher()
        fetcher._crawler = MagicMock()
        fetcher._crawler.close = AsyncMock()
        fetcher._initialized = True

        await fetcher.close()

        fetcher._crawler.close.assert_called_once()
        assert fetcher._initialized is False

    @pytest.mark.asyncio
    async def test_close_without_crawler(self):
        """Test close without crawler does nothing."""
        fetcher = Crawl4AIFetcher()
        fetcher._crawler = None
        fetcher._initialized = False

        # Should not raise
        await fetcher.close()
