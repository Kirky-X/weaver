# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for ingestion PlaywrightContextPool."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.fetching.playwright_pool import PlaywrightContextPool


class TestPlaywrightContextPoolInit:
    """Tests for PlaywrightContextPool initialization."""

    def test_default_initialization(self):
        """Test pool initializes with default parameters."""
        pool = PlaywrightContextPool()
        assert pool._pool_size == 5
        assert pool._page_pool_size == 3
        assert pool._stealth_enabled is True
        assert pool._pw is None
        assert pool._browser is None

    def test_custom_initialization(self):
        """Test pool initializes with custom parameters."""
        pool = PlaywrightContextPool(
            pool_size=10,
            page_pool_size=5,
            stealth_enabled=False,
            user_agent="Custom Agent",
            viewport_width=1366,
            viewport_height=768,
            locale="en-US",
            timezone="America/New_York",
            random_delay_min=1.0,
            random_delay_max=3.0,
        )
        assert pool._pool_size == 10
        assert pool._page_pool_size == 5
        assert pool._stealth_enabled is False
        assert pool._user_agent == "Custom Agent"
        assert pool._viewport_width == 1366
        assert pool._viewport_height == 768
        assert pool._locale == "en-US"
        assert pool._timezone == "America/New_York"
        assert pool._random_delay_min == 1.0
        assert pool._random_delay_max == 3.0


class TestPlaywrightContextPoolStartup:
    """Tests for startup method."""

    @pytest.mark.asyncio
    async def test_startup_creates_contexts(self):
        """Test startup creates browser contexts."""
        with patch("modules.ingestion.fetching.playwright_pool.Stealth") as mock_stealth_class:
            mock_stealth_instance = MagicMock()
            mock_stealth_instance.apply_stealth_async = AsyncMock()
            mock_stealth_class.return_value = mock_stealth_instance

            pool = PlaywrightContextPool(pool_size=2, page_pool_size=2)

            with patch("modules.ingestion.fetching.playwright_pool.async_playwright") as mock_pw:
                mock_pw_instance = MagicMock()
                mock_browser = MagicMock()
                mock_context = MagicMock()
                mock_page = MagicMock()

                mock_pw.return_value.start = AsyncMock(return_value=mock_pw_instance)
                mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_browser.new_context = AsyncMock(return_value=mock_context)
                mock_context.new_page = AsyncMock(return_value=mock_page)

                await pool.startup()

                mock_pw_instance.chromium.launch.assert_called_once()
                assert mock_browser.new_context.call_count == 2

    @pytest.mark.asyncio
    async def test_startup_with_stealth_disabled(self):
        """Test startup with stealth disabled."""
        pool = PlaywrightContextPool(pool_size=1, stealth_enabled=False)

        with patch("modules.ingestion.fetching.playwright_pool.async_playwright") as mock_pw:
            mock_pw_instance = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()

            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_instance)
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)

            await pool.startup()

            mock_browser.new_context.assert_called_once()


class TestPlaywrightContextPoolShutdown:
    """Tests for shutdown method."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_all(self):
        """Test shutdown closes all contexts and browser."""
        pool = PlaywrightContextPool(pool_size=2)

        mock_context = MagicMock()
        mock_context.close = AsyncMock()

        mock_queue = MagicMock()
        mock_queue.empty = MagicMock(side_effect=[False, False, True])
        mock_queue.get = AsyncMock(return_value=mock_context)

        pool._pool = mock_queue
        pool._browser = MagicMock()
        pool._browser.close = AsyncMock()
        pool._pw = MagicMock()
        pool._pw.stop = AsyncMock()

        await pool.shutdown()

        mock_context.close.assert_called()
        pool._browser.close.assert_called_once()
        pool._pw.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_empty_pool(self):
        """Test shutdown handles empty pool."""
        pool = PlaywrightContextPool(pool_size=1)

        mock_queue = MagicMock()
        mock_queue.empty = MagicMock(return_value=True)
        pool._pool = mock_queue
        pool._browser = MagicMock()
        pool._browser.close = AsyncMock()
        pool._pw = MagicMock()
        pool._pw.stop = AsyncMock()

        await pool.shutdown()

        pool._browser.close.assert_called_once()
        pool._pw.stop.assert_called_once()


class TestPlaywrightContextPoolAcquire:
    """Tests for acquire context manager."""

    @pytest.mark.asyncio
    async def test_acquire_returns_context(self):
        """Test acquire returns a context."""
        pool = PlaywrightContextPool(pool_size=1)

        mock_context = MagicMock()
        mock_context.clear_cookies = AsyncMock()

        pool._pool = MagicMock()
        pool._pool.get = AsyncMock(return_value=mock_context)
        pool._pool.put = AsyncMock()

        async with pool.acquire() as ctx:
            assert ctx is mock_context

        mock_context.clear_cookies.assert_called_once()
        pool._pool.put.assert_called_once_with(mock_context)

    @pytest.mark.asyncio
    async def test_acquire_clears_cookies_on_return(self):
        """Test cookies are cleared after use."""
        pool = PlaywrightContextPool(pool_size=1)

        mock_context = MagicMock()
        mock_context.clear_cookies = AsyncMock()

        pool._pool = MagicMock()
        pool._pool.get = AsyncMock(return_value=mock_context)
        pool._pool.put = AsyncMock()

        async with pool.acquire():
            pass

        mock_context.clear_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_acquire_returns_context_on_exception(self):
        """Test context is returned even on exception."""
        pool = PlaywrightContextPool(pool_size=1)

        mock_context = MagicMock()
        mock_context.clear_cookies = AsyncMock()

        pool._pool = MagicMock()
        pool._pool.get = AsyncMock(return_value=mock_context)
        pool._pool.put = AsyncMock()

        try:
            async with pool.acquire():
                raise ValueError("Test error")
        except ValueError:
            pass

        mock_context.clear_cookies.assert_called_once()
        pool._pool.put.assert_called_once()


class TestPlaywrightContextPoolAcquirePage:
    """Tests for acquire_page context manager."""

    @pytest.mark.asyncio
    async def test_acquire_page_returns_page(self):
        """Test acquire_page returns a page."""
        pool = PlaywrightContextPool(pool_size=1, page_pool_size=1)

        mock_page = MagicMock()
        mock_page.goto = AsyncMock()

        pool._page_pool = MagicMock()
        pool._page_pool.get = AsyncMock(return_value=mock_page)
        pool._page_pool.put = AsyncMock()
        pool._active_pages = set()

        async with pool.acquire_page() as page:
            assert page is mock_page

        mock_page.goto.assert_called()

    @pytest.mark.asyncio
    async def test_acquire_page_tracks_active_pages(self):
        """Test active pages are tracked."""
        pool = PlaywrightContextPool(pool_size=1, page_pool_size=1)

        mock_page = MagicMock()
        mock_page.goto = AsyncMock()

        pool._page_pool = MagicMock()
        pool._page_pool.get = AsyncMock(return_value=mock_page)
        pool._page_pool.put = AsyncMock()
        pool._active_pages = set()

        async with pool.acquire_page() as page:
            assert page in pool._active_pages

        assert page not in pool._active_pages

    @pytest.mark.asyncio
    async def test_acquire_page_handles_goto_failure(self):
        """Test page is closed if goto fails."""
        pool = PlaywrightContextPool(pool_size=1, page_pool_size=1)

        mock_page = MagicMock()
        mock_page.goto = AsyncMock(side_effect=Exception("Navigation failed"))
        mock_page.close = AsyncMock()

        pool._page_pool = MagicMock()
        pool._page_pool.get = AsyncMock(return_value=mock_page)
        pool._page_pool.put = AsyncMock()
        pool._active_pages = set()

        async with pool.acquire_page():
            pass

        mock_page.close.assert_called()


class TestPlaywrightContextPoolStealth:
    """Tests for stealth functionality."""

    @pytest.mark.asyncio
    async def test_apply_stealth_to_page_when_enabled(self):
        """Test stealth is applied to page when enabled."""
        with patch("modules.ingestion.fetching.playwright_pool.Stealth") as mock_stealth_class:
            mock_stealth_instance = MagicMock()
            mock_stealth_instance.apply_stealth_async = AsyncMock()
            mock_stealth_class.return_value = mock_stealth_instance

            pool = PlaywrightContextPool(pool_size=1, stealth_enabled=True)
            mock_page = MagicMock()

            await pool.apply_stealth_to_page(mock_page)

            mock_stealth_instance.apply_stealth_async.assert_called()

    @pytest.mark.asyncio
    async def test_apply_stealth_to_page_when_disabled(self):
        """Test stealth is not applied when disabled."""
        pool = PlaywrightContextPool(pool_size=1, stealth_enabled=False)
        mock_page = MagicMock()

        await pool.apply_stealth_to_page(mock_page)

        # Should not raise or call anything


class TestPlaywrightContextPoolRandomDelay:
    """Tests for random_delay method."""

    @pytest.mark.asyncio
    async def test_random_delay_adds_delay(self):
        """Test random_delay actually delays."""
        pool = PlaywrightContextPool(
            pool_size=1,
            random_delay_min=0.1,
            random_delay_max=0.2,
        )

        start = time.monotonic()
        await pool.random_delay()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.1

    @pytest.mark.asyncio
    async def test_random_delay_zero_disabled(self):
        """Test random_delay with zero values is no-op."""
        pool = PlaywrightContextPool(
            pool_size=1,
            random_delay_min=0,
            random_delay_max=0,
        )

        start = time.monotonic()
        await pool.random_delay()
        elapsed = time.monotonic() - start

        # Should be very fast (no actual delay)
        assert elapsed < 0.1


class TestPlaywrightContextPoolStats:
    """Tests for get_page_stats method."""

    @pytest.mark.asyncio
    async def test_get_page_stats(self):
        """Test get_page_stats returns correct stats."""
        pool = PlaywrightContextPool(pool_size=2, page_pool_size=3)
        pool._page_pool = MagicMock()
        pool._page_pool.qsize = MagicMock(return_value=4)
        pool._active_pages = {MagicMock(), MagicMock()}

        stats = await pool.get_page_stats()

        assert stats["pool_size"] == 6  # 2 * 3
        assert stats["available_pages"] == 4
        assert stats["active_pages"] == 2
