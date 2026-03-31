# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Playwright Fetcher."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.fetching.playwright_fetcher import PlaywrightFetcher


class TestPlaywrightFetcherInit:
    """Test PlaywrightFetcher initialization."""

    def test_init(self):
        """Test basic initialization."""
        mock_pool = MagicMock()
        fetcher = PlaywrightFetcher(mock_pool)

        assert fetcher._pool == mock_pool

    def test_init_with_human_like_delay(self):
        """Test initialization with human_like_delay parameter."""
        mock_pool = MagicMock()
        fetcher = PlaywrightFetcher(mock_pool, human_like_delay=True)

        assert fetcher._human_like_delay is True

    def test_init_without_human_like_delay(self):
        """Test initialization without human_like_delay."""
        mock_pool = MagicMock()
        fetcher = PlaywrightFetcher(mock_pool, human_like_delay=False)

        assert fetcher._human_like_delay is False


class TestPlaywrightFetcherFetch:
    """Test PlaywrightFetcher fetch method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock Playwright context pool."""
        pool = MagicMock()
        pool.random_delay = AsyncMock()
        pool.apply_stealth_to_page = AsyncMock()
        # Explicitly delete acquire_page to prevent MagicMock from auto-creating it
        delattr(pool, "acquire_page")
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
        page.wait_for_load_state = AsyncMock()
        page.evaluate = AsyncMock()
        return page

    @pytest.fixture
    def mock_response(self):
        """Create mock response."""

        # Use a simple object instead of MagicMock to avoid attribute interception
        class MockResponse:
            def __init__(self):
                self.status = 200
                self.headers = {"Content-Type": "text/html", "X-Custom": "value"}

        return MockResponse()

    @pytest.fixture
    def fetcher(self, mock_pool):
        """Create PlaywrightFetcher instance."""
        return PlaywrightFetcher(mock_pool, human_like_delay=False)

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
    async def test_fetch_with_headers(
        self, fetcher, mock_pool, mock_context, mock_page, mock_response
    ):
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
        mock_page.goto = AsyncMock(side_effect=TimeoutError("Page load timeout"))
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)

        with pytest.raises(asyncio.TimeoutError):
            await fetcher.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_page_closed_on_success(
        self, fetcher, mock_pool, mock_context, mock_page, mock_response
    ):
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
            # Create a simple mock response
            class MockResponse:
                def __init__(self, status):
                    self.status = status
                    self.headers = {}

            mock_response = MockResponse(status_code)

            mock_page.goto = AsyncMock(return_value=mock_response)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_pool.acquire = MagicMock(return_value=mock_context)

            status, _, _ = await fetcher.fetch("https://example.com")

            assert status == status_code

    @pytest.mark.asyncio
    async def test_fetch_without_headers(
        self, fetcher, mock_pool, mock_context, mock_page, mock_response
    ):
        """Test fetch without custom headers."""
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)

        await fetcher.fetch("https://example.com")

        mock_page.set_extra_http_headers.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_applies_stealth_to_page(
        self, fetcher, mock_pool, mock_context, mock_page, mock_response
    ):
        """Test stealth is applied to page."""
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_pool.acquire = MagicMock(return_value=mock_context)

        await fetcher.fetch("https://example.com")

        mock_pool.apply_stealth_to_page.assert_called_once_with(mock_page)


class TestPlaywrightFetcherHumanLike:
    """Tests for human-like behavior simulation."""

    @pytest.fixture
    def mock_pool_with_delay(self):
        """Create pool with delay enabled."""
        pool = MagicMock()
        pool.random_delay = AsyncMock()
        pool.apply_stealth_to_page = AsyncMock()
        # Explicitly delete acquire_page to prevent MagicMock from auto-creating it
        delattr(pool, "acquire_page")
        return pool

    @pytest.fixture
    def mock_page_for_human(self):
        """Create mock page for human-like tests."""
        page = MagicMock()
        page.set_extra_http_headers = AsyncMock()
        page.goto = AsyncMock()
        page.content = AsyncMock(return_value="<html></html>")
        page.close = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.evaluate = AsyncMock()
        return page

    @pytest.fixture
    def mock_context_for_human(self):
        """Create mock context for human-like tests."""
        context = MagicMock()
        context.new_page = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=context)
        context.__aexit__ = AsyncMock(return_value=None)
        return context

    @pytest.mark.asyncio
    async def test_human_like_delay_called(
        self, mock_pool_with_delay, mock_page_for_human, mock_context_for_human
    ):
        """Test random delay is called when human_like_delay is enabled."""
        fetcher = PlaywrightFetcher(mock_pool_with_delay, human_like_delay=True)

        class MockResponse:
            def __init__(self):
                self.status = 200
                self.headers = {}

        mock_response = MockResponse()

        mock_page_for_human.goto = AsyncMock(return_value=mock_response)
        mock_context_for_human.new_page = AsyncMock(return_value=mock_page_for_human)
        mock_pool_with_delay.acquire = MagicMock(return_value=mock_context_for_human)

        await fetcher.fetch("https://example.com")

        mock_pool_with_delay.random_delay.assert_called()

    @pytest.mark.asyncio
    async def test_human_like_delay_not_called_when_disabled(
        self, mock_pool_with_delay, mock_page_for_human, mock_context_for_human
    ):
        """Test random delay is not called when human_like_delay is disabled."""
        fetcher = PlaywrightFetcher(mock_pool_with_delay, human_like_delay=False)

        class MockResponse:
            def __init__(self):
                self.status = 200
                self.headers = {}

        mock_response = MockResponse()

        mock_page_for_human.goto = AsyncMock(return_value=mock_response)
        mock_context_for_human.new_page = AsyncMock(return_value=mock_page_for_human)
        mock_pool_with_delay.acquire = MagicMock(return_value=mock_context_for_human)

        await fetcher.fetch("https://example.com")

        mock_pool_with_delay.random_delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_for_content_called_when_enabled(
        self, mock_pool_with_delay, mock_page_for_human, mock_context_for_human
    ):
        """Test _wait_for_content is called when human_like_delay is enabled."""
        fetcher = PlaywrightFetcher(mock_pool_with_delay, human_like_delay=True)

        class MockResponse:
            def __init__(self):
                self.status = 200
                self.headers = {}

        mock_response = MockResponse()

        mock_page_for_human.goto = AsyncMock(return_value=mock_response)
        mock_context_for_human.new_page = AsyncMock(return_value=mock_page_for_human)
        mock_pool_with_delay.acquire = MagicMock(return_value=mock_context_for_human)

        await fetcher.fetch("https://example.com")

        mock_page_for_human.wait_for_load_state.assert_called()

    @pytest.mark.asyncio
    async def test_scroll_triggered_when_enabled(
        self, mock_pool_with_delay, mock_page_for_human, mock_context_for_human
    ):
        """Test scroll is triggered when human_like_delay is enabled."""
        fetcher = PlaywrightFetcher(mock_pool_with_delay, human_like_delay=True)

        class MockResponse:
            def __init__(self):
                self.status = 200
                self.headers = {}

        mock_response = MockResponse()

        mock_page_for_human.goto = AsyncMock(return_value=mock_response)
        mock_context_for_human.new_page = AsyncMock(return_value=mock_page_for_human)
        mock_pool_with_delay.acquire = MagicMock(return_value=mock_context_for_human)

        await fetcher.fetch("https://example.com")

        assert mock_page_for_human.evaluate.call_count >= 2


class TestPlaywrightFetcherClose:
    """Test PlaywrightFetcher close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method (no-op)."""
        fetcher = PlaywrightFetcher(MagicMock())

        await fetcher.close()
