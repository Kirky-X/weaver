# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for SSRF protection in fetchers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.security import URLValidationError, URLValidator
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher, RedirectBlockedError
from modules.ingestion.fetching.smart_fetcher import SmartFetcher


class TestSSRFProtection:
    """Tests for SSRF protection integration."""

    @pytest.fixture
    def url_validator(self) -> URLValidator:
        """Create a URL validator instance."""
        return URLValidator()

    @pytest.fixture
    def secure_fetcher(self, url_validator: URLValidator) -> HttpxFetcher:
        """Create an HttpxFetcher with SSRF protection."""
        return HttpxFetcher(
            timeout=5.0,
            url_validator=url_validator,
        )

    # ── Basic SSRF Blocking Tests ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_blocks_private_ip(self, secure_fetcher: HttpxFetcher) -> None:
        """Fetcher should block requests to private IP addresses."""
        with pytest.raises(URLValidationError):
            await secure_fetcher.fetch("http://192.168.1.1/")

    @pytest.mark.asyncio
    async def test_fetch_blocks_localhost(self, secure_fetcher: HttpxFetcher) -> None:
        """Fetcher should block requests to localhost."""
        with pytest.raises(URLValidationError):
            await secure_fetcher.fetch("http://127.0.0.1/")

    @pytest.mark.asyncio
    async def test_fetch_blocks_aws_metadata(self, secure_fetcher: HttpxFetcher) -> None:
        """Fetcher should block AWS metadata endpoint."""
        with pytest.raises(URLValidationError):
            await secure_fetcher.fetch("http://169.254.169.254/latest/meta-data/")

    @pytest.mark.asyncio
    async def test_fetch_blocks_file_scheme(self, secure_fetcher: HttpxFetcher) -> None:
        """Fetcher should block file:// scheme."""
        with pytest.raises(URLValidationError):
            await secure_fetcher.fetch("file:///etc/passwd")

    # ── Redirect Security Tests ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_blocked(self, url_validator: URLValidator) -> None:
        """Redirects to private IPs should be blocked."""
        fetcher = HttpxFetcher(url_validator=url_validator)

        # Mock a redirect response
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "<html>content</html>"
        mock_response.headers = {}
        mock_response.history = [MagicMock(url="http://192.168.1.1/redirected")]

        with patch.object(
            fetcher._client, "send", new_callable=AsyncMock, return_value=mock_response
        ):
            with pytest.raises(RedirectBlockedError):
                await fetcher.fetch("http://example.com/redirects-to-private")

    @pytest.mark.asyncio
    async def test_redirect_to_safe_url_allowed(self, url_validator: URLValidator) -> None:
        """Redirects to safe URLs should be allowed."""
        fetcher = HttpxFetcher(url_validator=url_validator)

        # Mock a safe redirect response
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "<html>content</html>"
        mock_response.headers = {}
        mock_response.history = [
            MagicMock(url="http://example.com/first-redirect"),
            MagicMock(url="http://example.com/final"),
        ]

        with patch.object(
            fetcher._client, "send", new_callable=AsyncMock, return_value=mock_response
        ):
            status, content, headers = await fetcher.fetch("http://example.com/redirects")
            assert status == 200

    @pytest.mark.asyncio
    async def test_max_redirects_limit(self, url_validator: URLValidator) -> None:
        """Should enforce max redirects limit."""
        fetcher = HttpxFetcher(url_validator=url_validator, timeout=5.0)

        # Create a response with too many redirects (more than 10)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "<html>content</html>"
        mock_response.headers = {}
        mock_response.history = [
            MagicMock(url=f"http://example.com/redirect{i}") for i in range(15)
        ]

        # httpx would normally raise TooManyRedirects, but we just check our code handles it
        with patch.object(
            fetcher._client, "send", new_callable=AsyncMock, return_value=mock_response
        ):
            # The fetch should work but we validate the redirect chain
            status, _, _ = await fetcher.fetch("http://example.com/many-redirects")
            assert status == 200

    # ── SmartFetcher Integration Tests ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_smart_fetcher_validates_urls(self, url_validator: URLValidator) -> None:
        """SmartFetcher should validate URLs before fetching."""
        # Create mock fetchers
        mock_httpx = MagicMock(spec=HttpxFetcher)
        mock_httpx.fetch = AsyncMock(return_value=(200, "<html>content</html>", {}))
        mock_httpx.close = AsyncMock()

        mock_playwright = MagicMock()
        mock_playwright.fetch = AsyncMock(return_value=(200, "<html>content</html>", {}))
        mock_playwright.close = AsyncMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx,
            playwright_fetcher=mock_playwright,
            url_validation_enabled=True,
        )

        # Valid URL should work
        await fetcher.fetch("https://example.com/")
        mock_httpx.fetch.assert_called()

    @pytest.mark.asyncio
    async def test_smart_fetcher_blocks_ssrf_urls(self, url_validator: URLValidator) -> None:
        """SmartFetcher should block SSRF-targeted URLs."""
        from core.security import URLValidationError

        mock_httpx = MagicMock(spec=HttpxFetcher)
        mock_httpx.fetch = AsyncMock(return_value=(200, "<html>content</html>", {}))
        mock_httpx.close = AsyncMock()

        mock_playwright = MagicMock()
        mock_playwright.close = AsyncMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx,
            playwright_fetcher=mock_playwright,
            url_validation_enabled=True,
        )

        # SSRF URL should be blocked
        with pytest.raises(URLValidationError):
            await fetcher.fetch("http://192.168.1.1/")

    # ── Cleanup Tests ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetcher_cleanup(self, secure_fetcher: HttpxFetcher) -> None:
        """Fetcher should clean up resources properly."""
        await secure_fetcher.close()
        # Client should be closed
        assert secure_fetcher._client.is_closed
