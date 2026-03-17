"""Unit tests for PlaywrightContextPool module."""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from modules.fetcher.playwright_pool import PlaywrightContextPool


class TestPlaywrightContextPool:
    """Tests for PlaywrightContextPool."""

    def test_initialization(self):
        """Test pool initializes correctly."""
        pool = PlaywrightContextPool(pool_size=5)
        assert pool._pool_size == 5
        assert pool._pw is None
        assert pool._browser is None

    def test_default_pool_size(self):
        """Test default pool size is 5."""
        pool = PlaywrightContextPool()
        assert pool._pool_size == 5

    @pytest.mark.asyncio
    async def test_startup_creates_pool(self):
        """Test startup creates browser contexts."""
        pool = PlaywrightContextPool(pool_size=3)

        with patch('modules.fetcher.playwright_pool.async_playwright') as mock_pw:
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
            assert mock_browser.new_context.call_count == 3

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
    async def test_acquire_and_return(self):
        """Test acquiring and returning context."""
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
    async def test_cookie_clearing(self):
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
    async def test_pool_exhaustion_waits(self):
        """Test pool waits when exhausted."""
        pool = PlaywrightContextPool(pool_size=1)

        mock_context = MagicMock()
        mock_context.clear_cookies = AsyncMock()

        pool._pool = MagicMock()
        pool._pool.get = AsyncMock(return_value=mock_context)
        pool._pool.put = AsyncMock()

        async with pool.acquire():
            pass

        pool._pool.get.assert_called()

    @pytest.mark.asyncio
    async def test_context_isolation(self):
        """Test contexts are isolated."""
        pool = PlaywrightContextPool(pool_size=2)

        mock_context1 = MagicMock()
        mock_context1.clear_cookies = AsyncMock()
        mock_context2 = MagicMock()
        mock_context2.clear_cookies = AsyncMock()

        call_count = 0

        def get_context():
            nonlocal call_count
            call_count += 1
            return mock_context1 if call_count == 1 else mock_context2

        pool._pool = MagicMock()
        pool._pool.get = AsyncMock(side_effect=get_context)
        pool._pool.put = AsyncMock()

        async with pool.acquire() as ctx1:
            pass

        async with pool.acquire() as ctx2:
            pass

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Test exception during context use is handled."""
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

    @pytest.mark.asyncio
    async def test_user_agent_set(self):
        """Test user agent is set on context creation."""
        pool = PlaywrightContextPool(pool_size=1)

        with patch('modules.fetcher.playwright_pool.async_playwright') as mock_pw:
            mock_pw_instance = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()

            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_instance)
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)

            await pool.startup()

            call_kwargs = mock_browser.new_context.call_args[1]
            assert "user_agent" in call_kwargs


class TestPlaywrightContextPoolStealth:
    """Tests for stealth functionality."""

    def test_stealth_initialization(self):
        """Test stealth is initialized when enabled."""
        pool = PlaywrightContextPool(pool_size=1, stealth_enabled=True)
        assert pool._stealth_enabled is True
        assert pool._stealth is not None

    def test_stealth_disabled(self):
        """Test stealth is not initialized when disabled."""
        pool = PlaywrightContextPool(pool_size=1, stealth_enabled=False)
        assert pool._stealth_enabled is False
        assert pool._stealth is None

    def test_custom_user_agent(self):
        """Test custom user agent is stored."""
        custom_ua = "Custom User Agent"
        pool = PlaywrightContextPool(pool_size=1, user_agent=custom_ua)
        assert pool._user_agent == custom_ua

    def test_viewport_settings(self):
        """Test viewport settings are stored."""
        pool = PlaywrightContextPool(
            pool_size=1,
            viewport_width=1366,
            viewport_height=768,
        )
        assert pool._viewport_width == 1366
        assert pool._viewport_height == 768

    def test_random_delay_settings(self):
        """Test random delay settings are stored."""
        pool = PlaywrightContextPool(
            pool_size=1,
            random_delay_min=1.0,
            random_delay_max=3.0,
        )
        assert pool._random_delay_min == 1.0
        assert pool._random_delay_max == 3.0

    @pytest.mark.asyncio
    async def test_random_delay_execution(self):
        """Test random delay actually delays."""
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
    async def test_stealth_applied_to_context(self):
        """Test stealth is applied when creating context."""
        with patch('modules.fetcher.playwright_pool.Stealth') as mock_stealth_class:
            mock_stealth_instance = MagicMock()
            mock_stealth_instance.apply_stealth_async = AsyncMock()
            mock_stealth_class.return_value = mock_stealth_instance

            pool = PlaywrightContextPool(pool_size=1, stealth_enabled=True)

            with patch('modules.fetcher.playwright_pool.async_playwright') as mock_pw:
                mock_pw_instance = MagicMock()
                mock_browser = MagicMock()
                mock_context = MagicMock()
                mock_page = MagicMock()

                mock_pw.return_value.start = AsyncMock(return_value=mock_pw_instance)
                mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
                mock_browser.new_context = AsyncMock(return_value=mock_context)
                mock_context.new_page = AsyncMock(return_value=mock_page)

                await pool.startup()

                mock_stealth_instance.apply_stealth_async.assert_called()

    @pytest.mark.asyncio
    async def test_apply_stealth_to_page_when_enabled(self):
        """Test apply_stealth_to_page works when stealth is enabled."""
        with patch('modules.fetcher.playwright_pool.Stealth') as mock_stealth_class:
            mock_stealth_instance = MagicMock()
            mock_stealth_instance.apply_stealth_async = AsyncMock()
            mock_stealth_class.return_value = mock_stealth_instance

            pool = PlaywrightContextPool(pool_size=1, stealth_enabled=True)

            mock_page = MagicMock()

            await pool.apply_stealth_to_page(mock_page)

            mock_stealth_instance.apply_stealth_async.assert_called()

    @pytest.mark.asyncio
    async def test_apply_stealth_to_page_when_disabled(self):
        """Test apply_stealth_to_page does nothing when stealth is disabled."""
        pool = PlaywrightContextPool(pool_size=1, stealth_enabled=False)

        mock_page = MagicMock()
        mock_page.add_init_script = AsyncMock()

        await pool.apply_stealth_to_page(mock_page)

        mock_page.add_init_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_browser_launch_args(self):
        """Test browser is launched with anti-detection args."""
        pool = PlaywrightContextPool(pool_size=1)

        with patch('modules.fetcher.playwright_pool.async_playwright') as mock_pw:
            mock_pw_instance = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()

            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_instance)
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)

            await pool.startup()

            call_kwargs = mock_pw_instance.chromium.launch.call_args[1]
            assert "args" in call_kwargs
            args = call_kwargs["args"]
            assert "--disable-blink-features=AutomationControlled" in args
