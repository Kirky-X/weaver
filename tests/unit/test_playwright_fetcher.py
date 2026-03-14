"""Unit tests for Playwright Fetcher."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from modules.fetcher.playwright_fetcher import PlaywrightFetcher


class TestPlaywrightFetcherInit:
    """Test PlaywrightFetcher initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        fetcher = PlaywrightFetcher(mock_pool)
        
        assert fetcher._pool == mock_pool


class TestPlaywrightFetcherFetch:
    """Test PlaywrightFetcher fetch method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Playwright context pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def mock_context(self):
        """Create mock browser context."""
        context = MagicMock()
        context.new_page = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=context)
        context.__aexit__ = AsyncMock(return_value=None)
        return context

    @pytest.fixture
    def mock_page(self):
        """Create mock page."""
        page = MagicMock()
        page.set_extra_http_headers = AsyncMock()
        page.goto = AsyncMock()
        page.content = AsyncMock(return_value="<html><body>Test Content</body></html>")
        page.close = AsyncMock()
        return page

    @pytest.fixture
    def mock_response(self):
        """Create mock response."""
        response = MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "text/html", "X-Custom": "value"}
        return response

    @pytest.fixture
    def fetcher(self, mock_pool):
        """Create PlaywrightFetcher instance."""
        return PlaywrightFetcher(mock_pool)

    @pytest.mark.asyncio
    async def test_fetch_basic(self, fetcher, mock_pool, mock_context, mock_page, mock_response):
        """Test basic fetch operation."""
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        status, content, headers = await fetcher.fetch("https://example.com")
        
        assert status == 200
        assert "Test Content" in content
        assert headers["Content-Type"] == "text/html"

    @pytest.mark.asyncio
    async def test_fetch_with_headers(self, fetcher, mock_pool, mock_context, mock_page, mock_response):
        """Test fetch with custom headers."""
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        await fetcher.fetch("https://example.com", headers={"Authorization": "Bearer token"})
        
        mock_page.set_extra_http_headers.assert_called_once_with({"Authorization": "Bearer token"})

    @pytest.mark.asyncio
    async def test_fetch_no_response(self, fetcher, mock_pool, mock_context, mock_page):
        """Test fetch when goto returns no response."""
        mock_page.goto = AsyncMock(return_value=None)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        status, content, headers = await fetcher.fetch("https://example.com")
        
        assert status == 200
        assert headers == {}

    @pytest.mark.asyncio
    async def test_fetch_error(self, fetcher, mock_pool, mock_context, mock_page):
        """Test fetch error handling."""
        mock_page.goto = AsyncMock(side_effect=Exception("Navigation failed"))
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        with pytest.raises(Exception, match="Navigation failed"):
            await fetcher.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_timeout(self, fetcher, mock_pool, mock_context, mock_page):
        """Test fetch timeout handling."""
        mock_page.goto = AsyncMock(side_effect=asyncio.TimeoutError("Page load timeout"))
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        with pytest.raises(asyncio.TimeoutError):
            await fetcher.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_page_closed_on_success(self, fetcher, mock_pool, mock_context, mock_page, mock_response):
        """Test page is closed after successful fetch."""
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        await fetcher.fetch("https://example.com")
        
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_page_closed_on_error(self, fetcher, mock_pool, mock_context, mock_page):
        """Test page is closed even on error."""
        mock_page.goto = AsyncMock(side_effect=Exception("Error"))
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        try:
            await fetcher.fetch("https://example.com")
        except Exception:
            pass
        
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_various_status_codes(self, fetcher, mock_pool, mock_context, mock_page):
        """Test various status codes."""
        for status_code in [200, 201, 301, 404, 500]:
            mock_response = MagicMock()
            mock_response.status = status_code
            mock_response.headers = {}
            
            mock_page.goto = AsyncMock(return_value=mock_response)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_pool.acquire = MagicMock(return_value=mock_context)
            
            status, _, _ = await fetcher.fetch("https://example.com")
            
            assert status == status_code

    @pytest.mark.asyncio
    async def test_fetch_without_headers(self, fetcher, mock_pool, mock_context, mock_page, mock_response):
        """Test fetch without custom headers."""
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)
        
        await fetcher.fetch("https://example.com")
        
        mock_page.set_extra_http_headers.assert_not_called()


class TestPlaywrightFetcherClose:
    """Test PlaywrightFetcher close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        fetcher = PlaywrightFetcher(MagicMock())
        
        await fetcher.close()
