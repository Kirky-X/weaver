# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SmartFetcher (ingestion module)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.resilience.circuit_breaker import CBState
from modules.ingestion.fetching.exceptions import CircuitOpenError
from modules.ingestion.fetching.smart_fetcher import (
    MIN_CONTENT_LENGTH,
    SmartFetcher,
    _appears_to_be_spa,
)


class TestSPADetection:
    """Test SPA detection function."""

    def test_empty_root_element_app(self):
        """Test detection of empty root element with id='app'."""
        html = '<html><body><div id="app"></div></body></html>'
        assert _appears_to_be_spa(html) is True

    def test_empty_root_element_root(self):
        """Test detection of empty root element with id='root'."""
        html = '<html><body><div id="root"></div></body></html>'
        assert _appears_to_be_spa(html) is True

    def test_framework_signature_next(self):
        """Test detection of Next.js signature."""
        html = "<html><body><script>__NEXT_DATA__ = {}</script></body></html>"
        assert _appears_to_be_spa(html) is True

    def test_framework_signature_nuxt(self):
        """Test detection of Nuxt.js signature."""
        html = "<html><body><script>__NUXT__ = {}</script></body></html>"
        assert _appears_to_be_spa(html) is True

    def test_framework_signature_angular(self):
        """Test detection of Angular signature."""
        html = '<html><body ng-version="15.0.0"></body></html>'
        assert _appears_to_be_spa(html) is True

    def test_framework_signature_react(self):
        """Test detection of React signature."""
        html = '<html><body><div data-reactroot=""></div></body></html>'
        assert _appears_to_be_spa(html) is True

    def test_script_heavy_low_content(self):
        """Test detection of script-heavy low-content pages."""
        html = "<html><body>" + '<script src="a.js"></script>' * 10 + "</body></html>"
        assert _appears_to_be_spa(html) is True

    def test_normal_page_not_spa(self):
        """Test normal page is not detected as SPA."""
        html = "<html><body><article><p>This is a long article content with enough text to not be considered SPA.</p></article></body></html>"
        assert _appears_to_be_spa(html) is False


class TestSmartFetcherInit:
    """Test SmartFetcher initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        mock_httpx = MagicMock()
        mock_crawl4ai = MagicMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx,
            crawl4ai_fetcher=mock_crawl4ai,
        )

        assert fetcher._httpx == mock_httpx
        assert fetcher._crawl4ai == mock_crawl4ai
        assert fetcher._circuit_breaker_enabled is True
        assert fetcher._breakers == {}

    def test_init_with_circuit_breaker_params(self):
        """Test initialization with circuit breaker params."""
        mock_httpx = MagicMock()
        mock_crawl4ai = MagicMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx,
            crawl4ai_fetcher=mock_crawl4ai,
            circuit_breaker_threshold=5,
            circuit_breaker_timeout=30.0,
            circuit_breaker_enabled=False,
        )

        assert fetcher._circuit_breaker_threshold == 5
        assert fetcher._circuit_breaker_timeout == 30.0
        assert fetcher._circuit_breaker_enabled is False

    def test_init_with_rate_limiter(self):
        """Test initialization with rate limiter."""
        mock_httpx = MagicMock()
        mock_crawl4ai = MagicMock()
        mock_rate_limiter = MagicMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx,
            crawl4ai_fetcher=mock_crawl4ai,
            rate_limiter=mock_rate_limiter,
        )

        assert fetcher._rate_limiter == mock_rate_limiter

    def test_min_content_length_constant(self):
        """Test MIN_CONTENT_LENGTH constant."""
        assert MIN_CONTENT_LENGTH == 500


class TestSmartFetcherGetBreaker:
    """Test SmartFetcher._get_breaker method."""

    @pytest.fixture
    def smart_fetcher(self):
        """Create SmartFetcher instance."""
        mock_httpx = MagicMock()
        mock_crawl4ai = MagicMock()
        return SmartFetcher(
            httpx_fetcher=mock_httpx,
            crawl4ai_fetcher=mock_crawl4ai,
        )

    def test_get_breaker_creates_new(self, smart_fetcher):
        """Test _get_breaker creates new breaker for new host."""
        breaker = smart_fetcher._get_breaker("example.com")

        assert breaker is not None
        assert "example.com" in smart_fetcher._breakers

    def test_get_breaker_returns_existing(self, smart_fetcher):
        """Test _get_breaker returns existing breaker for known host."""
        breaker1 = smart_fetcher._get_breaker("example.com")
        breaker2 = smart_fetcher._get_breaker("example.com")

        assert breaker1 is breaker2

    def test_get_breaker_different_hosts(self, smart_fetcher):
        """Test _get_breaker creates different breakers for different hosts."""
        breaker1 = smart_fetcher._get_breaker("example1.com")
        breaker2 = smart_fetcher._get_breaker("example2.com")

        assert breaker1 is not breaker2


class TestSmartFetcherFetch:
    """Test SmartFetcher.fetch method."""

    @pytest.fixture
    def mock_httpx_fetcher(self):
        """Create mock HttpxFetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(
            return_value=(
                200,
                "<html><body>Content long enough to pass minimum length requirement</body></html>",
                {},
            )
        )
        fetcher.close = AsyncMock()
        return fetcher

    @pytest.fixture
    def mock_crawl4ai_fetcher(self):
        """Create mock Crawl4AIFetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))
        fetcher.close = AsyncMock()
        return fetcher

    @pytest.fixture
    def smart_fetcher(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Create SmartFetcher with circuit breaker enabled."""
        return SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
            circuit_breaker_threshold=3,
            circuit_breaker_timeout=60.0,
        )

    @pytest.mark.asyncio
    async def test_fetch_success_httpx(self, smart_fetcher, mock_httpx_fetcher):
        """Test successful fetch via httpx."""
        status, content, headers = await smart_fetcher.fetch("https://example.com/article")

        assert status == 200
        assert "Content" in content
        mock_httpx_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_success_records_success(self, smart_fetcher, mock_httpx_fetcher):
        """Test successful fetch records success to circuit breaker."""
        await smart_fetcher.fetch("https://example.com/article")

        breaker = smart_fetcher._get_breaker("example.com")
        assert breaker.state == CBState.CLOSED
        assert breaker._fail_count == 0

    @pytest.mark.asyncio
    async def test_fetch_failure_records_failure(
        self, smart_fetcher, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test failed fetch records failure to circuit breaker."""
        mock_httpx_fetcher.fetch.side_effect = ConnectionError("Network error")
        mock_crawl4ai_fetcher.fetch.side_effect = ConnectionError("Network error")

        with pytest.raises(ConnectionError):
            await smart_fetcher.fetch("https://example.com/article")

        breaker = smart_fetcher._get_breaker("example.com")
        assert breaker._fail_count == 1

    @pytest.mark.asyncio
    async def test_fetch_force_browser_skips_httpx(
        self, smart_fetcher, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test force_browser=True skips httpx and uses crawl4ai directly."""
        await smart_fetcher.fetch("https://example.com/article", force_browser=True)

        mock_crawl4ai_fetcher.fetch.assert_called_once()
        mock_httpx_fetcher.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_spa_fallback_to_crawl4ai(
        self, smart_fetcher, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test SPA page triggers crawl4ai fallback."""
        mock_httpx_fetcher.fetch.return_value = (
            200,
            '<html><body><div id="app"></div></body></html>',
            {},
        )

        status, content, headers = await smart_fetcher.fetch("https://example.com/article")

        mock_httpx_fetcher.fetch.assert_called_once()
        mock_crawl4ai_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_short_content_fallback_to_crawl4ai(
        self, smart_fetcher, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test short content triggers crawl4ai fallback."""
        mock_httpx_fetcher.fetch.return_value = (200, "short", {})

        status, content, headers = await smart_fetcher.fetch("https://example.com/article")

        mock_httpx_fetcher.fetch.assert_called_once()
        mock_crawl4ai_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_httpx_error_fallback_to_crawl4ai(
        self, smart_fetcher, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test httpx error triggers crawl4ai fallback."""
        mock_httpx_fetcher.fetch.side_effect = Exception("httpx error")

        status, content, headers = await smart_fetcher.fetch("https://example.com/article")

        mock_httpx_fetcher.fetch.assert_called_once()
        mock_crawl4ai_fetcher.fetch.assert_called_once()
        assert status == 200

    @pytest.mark.asyncio
    async def test_circuit_open_raises_circuit_open_error(
        self, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test open circuit raises CircuitOpenError."""
        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
            circuit_breaker_threshold=1,
            circuit_breaker_timeout=60.0,
        )

        mock_httpx_fetcher.fetch.side_effect = ConnectionError("Network error")
        mock_crawl4ai_fetcher.fetch.side_effect = ConnectionError("Network error")

        # Trigger circuit open
        with pytest.raises(ConnectionError):
            await fetcher.fetch("https://example.com/article")

        # Next request should raise CircuitOpenError
        with pytest.raises(CircuitOpenError) as exc_info:
            await fetcher.fetch("https://example.com/article2")

        assert exc_info.value.host == "example.com"

    @pytest.mark.asyncio
    async def test_circuit_per_host_isolation(self, smart_fetcher, mock_httpx_fetcher):
        """Test circuit breaker is isolated per host."""
        # Manually open circuit for example.com
        breaker = smart_fetcher._get_breaker("example.com")
        for _ in range(smart_fetcher._circuit_breaker_threshold):
            await breaker.record_failure()

        # example.com should be blocked
        with pytest.raises(CircuitOpenError):
            await smart_fetcher.fetch("https://example.com/article")

        # other.com should still work
        mock_httpx_fetcher.fetch.return_value = (
            200,
            "<html>content long enough to pass minimum</html>",
            {},
        )

        status, content, headers = await smart_fetcher.fetch("https://other.com/article")
        assert status == 200

    @pytest.mark.asyncio
    async def test_circuit_recovers_after_success(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Test circuit recovers after successful request."""
        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
            circuit_breaker_threshold=1,
            circuit_breaker_timeout=0.1,  # Short timeout for testing
        )

        mock_httpx_fetcher.fetch.side_effect = ConnectionError("Network error")
        mock_crawl4ai_fetcher.fetch.side_effect = ConnectionError("Network error")

        # Trigger circuit open
        with pytest.raises(ConnectionError):
            await fetcher.fetch("https://example.com/article")

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Reset mocks to succeed
        mock_httpx_fetcher.fetch.side_effect = None
        mock_httpx_fetcher.fetch.return_value = (
            200,
            "<html>content long enough to pass minimum length requirement</html>",
            {},
        )
        mock_crawl4ai_fetcher.fetch.side_effect = None
        mock_crawl4ai_fetcher.fetch.return_value = (200, "<html>content</html>", {})

        await fetcher.fetch("https://example.com/article2")

        breaker = fetcher._get_breaker("example.com")
        assert breaker.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_fetch_with_rate_limiter(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Test fetch with rate limiter."""
        mock_rate_limiter = MagicMock()
        mock_rate_limiter.acquire = AsyncMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
            rate_limiter=mock_rate_limiter,
        )

        await fetcher.fetch("https://example.com/article")

        mock_rate_limiter.acquire.assert_called_once_with("https://example.com/article")


class TestSmartFetcherCircuitBreakerDisabled:
    """Test SmartFetcher with circuit breaker disabled."""

    @pytest.fixture
    def mock_httpx_fetcher(self):
        """Create mock HttpxFetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=(200, "<html>content</html>", {}))
        fetcher.close = AsyncMock()
        return fetcher

    @pytest.fixture
    def mock_crawl4ai_fetcher(self):
        """Create mock Crawl4AIFetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=(200, "<html>content</html>", {}))
        fetcher.close = AsyncMock()
        return fetcher

    @pytest.fixture
    def smart_fetcher_no_cb(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Create SmartFetcher with circuit breaker disabled."""
        return SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
            circuit_breaker_enabled=False,
        )

    @pytest.mark.asyncio
    async def test_no_circuit_breaker_check(self, smart_fetcher_no_cb, mock_httpx_fetcher):
        """Test no circuit breaker check when disabled."""
        # Even if breaker exists, should not check
        smart_fetcher_no_cb._get_breaker("example.com")

        await smart_fetcher_no_cb.fetch("https://example.com/article")

        # Should succeed without circuit breaker check
        mock_httpx_fetcher.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_failure_recording(
        self, smart_fetcher_no_cb, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test no failure recording when circuit breaker disabled."""
        mock_httpx_fetcher.fetch.side_effect = RuntimeError("error")
        mock_crawl4ai_fetcher.fetch.side_effect = RuntimeError("error")

        with pytest.raises(RuntimeError):
            await smart_fetcher_no_cb.fetch("https://example.com/article")

        # Breaker should still be closed (not recording failures)
        breaker = smart_fetcher_no_cb._get_breaker("example.com")
        assert breaker.state == CBState.CLOSED


class TestSmartFetcherClose:
    """Test SmartFetcher close method."""

    @pytest.fixture
    def mock_httpx_fetcher(self):
        """Create mock HttpxFetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock()
        fetcher.close = AsyncMock()
        return fetcher

    @pytest.fixture
    def mock_crawl4ai_fetcher(self):
        """Create mock Crawl4AIFetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock()
        fetcher.close = AsyncMock()
        return fetcher

    @pytest.fixture
    def smart_fetcher(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Create SmartFetcher instance."""
        return SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
        )

    @pytest.mark.asyncio
    async def test_close_calls_underlying_fetchers(
        self, smart_fetcher, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test close() calls close on underlying fetchers."""
        await smart_fetcher.close()

        mock_httpx_fetcher.close.assert_called_once()
        mock_crawl4ai_fetcher.close.assert_called_once()
