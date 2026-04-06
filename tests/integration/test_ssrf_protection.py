# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for SSRF protection in fetchers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.security.validator import URLValidator, URLValidatorConfig
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
from modules.ingestion.fetching.smart_fetcher import SmartFetcher


class TestSSRFProtection:
    """Tests for SSRF protection integration."""

    @pytest.fixture
    def url_validator_config(self) -> URLValidatorConfig:
        """Create a URL validator config instance."""
        return URLValidatorConfig(
            enabled=True,
            urlhaus_api_key="",
            phishtank_enabled=False,
        )

    @pytest.fixture
    def httpx_fetcher(self) -> HttpxFetcher:
        """Create a basic HttpxFetcher for URL validation."""
        return HttpxFetcher(timeout=5.0)

    @pytest.fixture
    def url_validator(
        self, url_validator_config: URLValidatorConfig, httpx_fetcher: HttpxFetcher
    ) -> URLValidator:
        """Create a URL validator instance."""
        return URLValidator(
            config=url_validator_config,
            fetcher=httpx_fetcher,
            redis_client=None,
        )

    # ── URL Validation Tests ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_url_validator_initialization(self, url_validator: URLValidator) -> None:
        """Test URL validator can be initialized."""
        assert url_validator._config.enabled is True

    @pytest.mark.asyncio
    async def test_url_validator_config_defaults(self) -> None:
        """Test URL validator config defaults."""
        config = URLValidatorConfig()
        assert config.enabled is True
        assert config.urlhaus_api_key == ""
        assert config.phishtank_enabled is True

    # ── HttpxFetcher Tests ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_httpx_fetcher_initialization(self) -> None:
        """Test HttpxFetcher can be initialized."""
        fetcher = HttpxFetcher(timeout=10.0)
        assert fetcher._client is not None

    @pytest.mark.asyncio
    async def test_httpx_fetcher_with_url_validator(self, url_validator: URLValidator) -> None:
        """Test HttpxFetcher can accept URL validator."""
        fetcher = HttpxFetcher(timeout=5.0, url_validator=url_validator)
        assert fetcher._url_validator is url_validator

    # ── SmartFetcher Tests ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_smart_fetcher_initialization(self) -> None:
        """Test SmartFetcher can be initialized."""
        mock_httpx = MagicMock(spec=HttpxFetcher)
        mock_httpx.close = AsyncMock()

        mock_crawl4ai = MagicMock()
        mock_crawl4ai.close = AsyncMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx,
            crawl4ai_fetcher=mock_crawl4ai,
        )
        assert fetcher._httpx is mock_httpx

    @pytest.mark.asyncio
    async def test_smart_fetcher_with_url_validator(self, url_validator: URLValidator) -> None:
        """Test SmartFetcher can accept URL validator."""
        mock_httpx = MagicMock(spec=HttpxFetcher)
        mock_httpx.close = AsyncMock()

        mock_crawl4ai = MagicMock()
        mock_crawl4ai.close = AsyncMock()

        fetcher = SmartFetcher(
            httpx_fetcher=mock_httpx,
            crawl4ai_fetcher=mock_crawl4ai,
            url_validator=url_validator,
        )
        assert fetcher._url_validator is url_validator

    # ── SSRFChecker Tests ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ssrf_checker_is_safe_url(self) -> None:
        """Test SSRFChecker is_safe_url method."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Public URLs should be considered safe (synchronous check)
        assert checker.is_safe_url("https://example.com") is True
        assert checker.is_safe_url("https://google.com") is True

    @pytest.mark.asyncio
    async def test_ssrf_checker_blocks_private_urls(self) -> None:
        """Test SSRFChecker blocks private IPs."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Private IPs should be blocked
        assert checker.is_safe_url("http://192.168.1.1/") is False
        assert checker.is_safe_url("http://10.0.0.1/") is False
        assert checker.is_safe_url("http://127.0.0.1/") is False

    # ── Cleanup Tests ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetcher_cleanup(self) -> None:
        """Fetcher should clean up resources properly."""
        fetcher = HttpxFetcher(timeout=5.0)
        await fetcher.close()
        assert fetcher._client.is_closed
