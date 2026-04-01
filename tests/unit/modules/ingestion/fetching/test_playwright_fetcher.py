# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for ingestion PlaywrightFetcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.fetching.playwright_fetcher import PlaywrightFetcher


@pytest.fixture
def mock_pool():
    """Create mock PlaywrightContextPool."""
    pool = MagicMock()
    pool.apply_stealth_to_page = AsyncMock()
    pool.random_delay = AsyncMock()
    pool.acquire = MagicMock()
    pool.acquire_page = MagicMock()
    return pool


class TestPlaywrightFetcherInit:
    """Tests for PlaywrightFetcher initialization."""

    def test_init_with_defaults(self, mock_pool):
        """Test initialization with default parameters."""
        fetcher = PlaywrightFetcher(mock_pool)
        assert fetcher._pool is mock_pool
        assert fetcher._human_like_delay is True
        assert fetcher._use_page_pool is True

    def test_init_with_custom_params(self, mock_pool):
        """Test initialization with custom parameters."""
        fetcher = PlaywrightFetcher(
            pool=mock_pool,
            human_like_delay=False,
            use_page_pool=False,
        )
        assert fetcher._human_like_delay is False
        assert fetcher._use_page_pool is False


class TestPlaywrightFetcherFetch:
    """Tests for fetch method."""

    @pytest.mark.asyncio
    async def test_fetch_with_page_pool(self, mock_pool):
        """Test fetch using page pool."""
        fetcher = PlaywrightFetcher(mock_pool, use_page_pool=True)

        mock_page = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.content = AsyncMock(return_value="<html>test</html>")
        mock_page.set_extra_http_headers = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.evaluate = AsyncMock()

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_page)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_pool.acquire_page.return_value = mock_context

        status, content, headers = await fetcher.fetch("https://example.com")

        assert status == 200
        assert content == "<html>test</html>"

    @pytest.mark.asyncio
    async def test_fetch_with_context(self, mock_pool):
        """Test fetch using context when page pool disabled."""
        fetcher = PlaywrightFetcher(mock_pool, use_page_pool=False, human_like_delay=False)

        mock_page = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.content = AsyncMock(return_value="<html>test</html>")
        mock_page.set_extra_http_headers = AsyncMock()
        mock_page.close = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()

        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.__aenter__ = AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_pool.acquire.return_value = mock_context

        status, content, headers = await fetcher.fetch("https://example.com")

        assert status == 200
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_with_headers(self, mock_pool):
        """Test fetch passes custom headers."""
        fetcher = PlaywrightFetcher(mock_pool, use_page_pool=True, human_like_delay=False)

        mock_page = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.content = AsyncMock(return_value="<html>test</html>")
        mock_page.set_extra_http_headers = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_page)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_pool.acquire_page.return_value = mock_context

        await fetcher.fetch("https://example.com", headers={"X-Custom": "value"})

        mock_page.set_extra_http_headers.assert_called_once_with({"X-Custom": "value"})

    @pytest.mark.asyncio
    async def test_fetch_with_human_like_delay(self, mock_pool):
        """Test fetch adds human-like delay when enabled."""
        fetcher = PlaywrightFetcher(mock_pool, use_page_pool=True, human_like_delay=True)

        mock_page = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_page.goto = AsyncMock(return_value=mock_response)
        mock_page.content = AsyncMock(return_value="<html>test</html>")
        mock_page.set_extra_http_headers = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.evaluate = AsyncMock()

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_page)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_pool.acquire_page.return_value = mock_context

        await fetcher.fetch("https://example.com")

        # Should call random_delay multiple times
        assert mock_pool.random_delay.call_count >= 1

    @pytest.mark.asyncio
    async def test_fetch_handles_exception(self, mock_pool):
        """Test fetch propagates exceptions."""
        fetcher = PlaywrightFetcher(mock_pool, use_page_pool=True)

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(side_effect=Exception("Browser error"))
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_pool.acquire_page.return_value = mock_context

        with pytest.raises(Exception, match="Browser error"):
            await fetcher.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_null_response(self, mock_pool):
        """Test fetch handles null response."""
        fetcher = PlaywrightFetcher(mock_pool, use_page_pool=True, human_like_delay=False)

        mock_page = MagicMock()
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.content = AsyncMock(return_value="<html>test</html>")
        mock_page.set_extra_http_headers = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_page)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_pool.acquire_page.return_value = mock_context

        status, content, headers = await fetcher.fetch("https://example.com")

        # Should default to 200 when response is null
        assert status == 200


class TestPlaywrightFetcherWaitForContent:
    """Tests for _wait_for_content method."""

    @pytest.mark.asyncio
    async def test_wait_for_content_success(self, mock_pool):
        """Test _wait_for_content waits for network idle."""
        fetcher = PlaywrightFetcher(mock_pool)

        mock_page = MagicMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.evaluate = AsyncMock()

        await fetcher._wait_for_content(mock_page)

        mock_page.wait_for_load_state.assert_called_once()
        mock_pool.random_delay.assert_called()

    @pytest.mark.asyncio
    async def test_wait_for_content_handles_timeout(self, mock_pool):
        """Test _wait_for_content handles timeout gracefully."""
        fetcher = PlaywrightFetcher(mock_pool)

        mock_page = MagicMock()
        mock_page.wait_for_load_state = AsyncMock(side_effect=Exception("Timeout"))
        mock_page.evaluate = AsyncMock()

        # Should not raise
        await fetcher._wait_for_content(mock_page)


class TestPlaywrightFetcherClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_is_noop(self, mock_pool):
        """Test close is a no-op."""
        fetcher = PlaywrightFetcher(mock_pool)

        # Should not raise
        await fetcher.close()
