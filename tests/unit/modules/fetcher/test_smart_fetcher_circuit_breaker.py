# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SmartFetcher circuit breaker integration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.resilience.circuit_breaker import CBState
from modules.ingestion.fetching.exceptions import CircuitOpenError
from modules.ingestion.fetching.smart_fetcher import SmartFetcher


class TestSmartFetcherCircuitBreaker:
    """Tests for SmartFetcher circuit breaker functionality."""

    @pytest.fixture
    def mock_httpx_fetcher(self):
        """Create mock HttpxFetcher."""
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=(200, "<html><body>Content</body></html>", {}))
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

    def test_init_circuit_breaker_params(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Test SmartFetcher initializes with circuit breaker params."""
        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
            circuit_breaker_threshold=5,
            circuit_breaker_timeout=30.0,
        )

        assert fetcher._circuit_breaker_threshold == 5
        assert fetcher._circuit_breaker_timeout == 30.0
        assert fetcher._breakers == {}

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
    async def test_circuit_opens_after_threshold(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Test circuit opens after reaching failure threshold."""
        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx_fetcher,
            crawl4ai_fetcher=mock_crawl4ai_fetcher,
            circuit_breaker_threshold=2,
            circuit_breaker_timeout=60.0,
        )

        mock_httpx_fetcher.fetch.side_effect = ConnectionError("Network error")
        mock_crawl4ai_fetcher.fetch.side_effect = ConnectionError("Network error")

        # First failure
        with pytest.raises(ConnectionError):
            await fetcher.fetch("https://example.com/article1")

        # Second failure - triggers open
        with pytest.raises(ConnectionError):
            await fetcher.fetch("https://example.com/article2")

        breaker = fetcher._get_breaker("example.com")
        assert breaker.state == CBState.OPEN

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
        # Make example.com fail
        mock_httpx_fetcher.fetch.side_effect = ConnectionError("Network error")

        # Manually open circuit for example.com
        breaker = smart_fetcher._get_breaker("example.com")
        for _ in range(smart_fetcher._circuit_breaker_threshold):
            await breaker.record_failure()

        # example.com should be blocked
        with pytest.raises(CircuitOpenError):
            await smart_fetcher.fetch("https://example.com/article")

        # other.com should still work
        mock_httpx_fetcher.fetch.side_effect = None
        mock_httpx_fetcher.fetch.return_value = (200, "<html>content</html>", {})

        status, content, headers = await smart_fetcher.fetch("https://other.com/article")
        assert status == 200

    @pytest.mark.asyncio
    async def test_circuit_recovers_after_success(self, mock_httpx_fetcher, mock_crawl4ai_fetcher):
        """Test circuit recovers after successful request in half-open state."""
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

        # Reset both mocks to succeed
        mock_httpx_fetcher.fetch.side_effect = None
        mock_httpx_fetcher.fetch.return_value = (
            200,
            "<html>content long enough to pass</html>",
            {},
        )
        mock_crawl4ai_fetcher.fetch.side_effect = None
        mock_crawl4ai_fetcher.fetch.return_value = (200, "<html>content</html>", {})

        await fetcher.fetch("https://example.com/article2")

        breaker = fetcher._get_breaker("example.com")
        assert breaker.state == CBState.CLOSED

    @pytest.mark.asyncio
    async def test_close_calls_underlying_fetchers(
        self, smart_fetcher, mock_httpx_fetcher, mock_crawl4ai_fetcher
    ):
        """Test close() calls close on underlying fetchers."""
        await smart_fetcher.close()

        mock_httpx_fetcher.close.assert_called_once()
        mock_crawl4ai_fetcher.close.assert_called_once()
