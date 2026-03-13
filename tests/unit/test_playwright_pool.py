"""Unit tests for PlaywrightContextPool module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.fetcher.playwright_pool import PlaywrightContextPool


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
        
        with patch('core.fetcher.playwright_pool.async_playwright') as mock_pw:
            mock_pw_instance = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_instance)
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            
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
        
        with patch('core.fetcher.playwright_pool.async_playwright') as mock_pw:
            mock_pw_instance = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            
            mock_pw.return_value.start = AsyncMock(return_value=mock_pw_instance)
            mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            
            await pool.startup()
            
            call_kwargs = mock_browser.new_context.call_args[1]
            assert "user_agent" in call_kwargs
