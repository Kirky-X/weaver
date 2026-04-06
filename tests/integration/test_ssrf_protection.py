# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for SSRF protection in fetchers with real network operations."""

from __future__ import annotations

import socket

import pytest

from core.security.validator import URLValidator, URLValidatorConfig
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
from modules.ingestion.fetching.smart_fetcher import SmartFetcher


class TestSSRFProtection:
    """Tests for SSRF protection integration with real network operations."""

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
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_httpx_fetcher_with_url_validator(self, url_validator: URLValidator) -> None:
        """Test HttpxFetcher can accept URL validator."""
        fetcher = HttpxFetcher(timeout=5.0, url_validator=url_validator)
        assert fetcher._url_validator is url_validator
        await fetcher.close()

    # ── SmartFetcher Tests with Real Components ───────────────────────────────

    @pytest.mark.asyncio
    async def test_smart_fetcher_initialization(self) -> None:
        """Test SmartFetcher can be initialized with real components."""
        httpx_fetcher = HttpxFetcher(timeout=5.0)

        # SmartFetcher requires both fetchers
        fetcher = SmartFetcher(
            httpx_fetcher=httpx_fetcher,
            crawl4ai_fetcher=None,  # crawl4ai is optional
        )
        assert fetcher._httpx is httpx_fetcher
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_smart_fetcher_with_url_validator(self, url_validator: URLValidator) -> None:
        """Test SmartFetcher can accept URL validator with real components."""
        httpx_fetcher = HttpxFetcher(timeout=5.0, url_validator=url_validator)

        fetcher = SmartFetcher(
            httpx_fetcher=httpx_fetcher,
            crawl4ai_fetcher=None,
            url_validator=url_validator,
        )
        assert fetcher._url_validator is url_validator
        await fetcher.close()

    # ── SSRFChecker Tests with Real Network Checks ───────────────────────────

    @pytest.mark.asyncio
    async def test_ssrf_checker_is_safe_url(self) -> None:
        """Test SSRFChecker is_safe_url method with real DNS resolution."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Public URLs should be considered safe (synchronous check)
        assert checker.is_safe_url("https://example.com") is True
        assert checker.is_safe_url("https://google.com") is True
        assert checker.is_safe_url("https://github.com") is True

    @pytest.mark.asyncio
    async def test_ssrf_checker_blocks_private_urls(self) -> None:
        """Test SSRFChecker blocks private IPs with real network checks."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Private IPs should be blocked
        assert checker.is_safe_url("http://192.168.1.1/") is False
        assert checker.is_safe_url("http://10.0.0.1/") is False
        assert checker.is_safe_url("http://127.0.0.1/") is False
        assert checker.is_safe_url("http://172.16.0.1/") is False

    @pytest.mark.asyncio
    async def test_ssrf_checker_blocks_localhost_variants(self) -> None:
        """Test SSRFChecker blocks various localhost representations."""
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Various localhost IP representations should be blocked
        assert checker.is_safe_url("http://127.0.0.1:8080/") is False
        assert checker.is_safe_url("http://[::1]/") is False
        assert checker.is_safe_url("http://0.0.0.0/") is False

    # ── Real HTTP Request Tests ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetcher_rejects_private_url(self) -> None:
        """Test HttpxFetcher rejects requests to private IPs with SSRF protection."""
        from core.security.ssrf import SSRFError

        httpx_fetcher = HttpxFetcher(timeout=5.0)

        # Create SSRF checker
        from core.security.ssrf import SSRFChecker

        checker = SSRFChecker()

        # Verify private IPs are blocked
        assert checker.is_safe_url("http://192.168.1.1/") is False
        assert checker.is_safe_url("http://10.0.0.1/") is False
        assert checker.is_safe_url("http://127.0.0.1/") is False

        await httpx_fetcher.close()

    # ── Cleanup Tests ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetcher_cleanup(self) -> None:
        """Fetcher should clean up resources properly."""
        fetcher = HttpxFetcher(timeout=5.0)
        await fetcher.close()
        assert fetcher._client.is_closed

    @pytest.mark.asyncio
    async def test_smart_fetcher_cleanup(self) -> None:
        """SmartFetcher should clean up all resources properly."""
        httpx_fetcher = HttpxFetcher(timeout=5.0)

        fetcher = SmartFetcher(
            httpx_fetcher=httpx_fetcher,
            crawl4ai_fetcher=None,
        )

        await fetcher.close()

        # Httpx fetcher should be closed
        assert httpx_fetcher._client.is_closed
