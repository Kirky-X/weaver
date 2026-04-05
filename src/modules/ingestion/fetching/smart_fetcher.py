# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Smart fetcher that chooses between httpx and Playwright based on response."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from core.observability.logging import get_logger
from core.resilience.circuit_breaker import CircuitBreaker
from core.security import URLValidator
from modules.ingestion.fetching.base import BaseFetcher
from modules.ingestion.fetching.exceptions import CircuitOpenError
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
from modules.ingestion.fetching.playwright_fetcher import PlaywrightFetcher

if TYPE_CHECKING:
    from modules.ingestion.fetching.rate_limiter import HostRateLimiter

log = get_logger("smart_fetcher")

# Hosts that are known to require JavaScript rendering
JS_REQUIRED_HOSTS: set[str] = {
    "weibo.com",
    "m.weibo.cn",
    "mp.weixin.qq.com",
    "toutiao.com",
    "36kr.com",  # SPA-based tech news site
}

# Minimum content length to consider a page valid
MIN_CONTENT_LENGTH = 500


class SmartFetcher(BaseFetcher):
    """Intelligent fetcher that tries httpx first, falls back to Playwright.

    Strategy:
    1. If circuit breaker is open for host → raise CircuitOpenError.
    2. If host is known to need JS → use Playwright directly.
    3. Otherwise → try httpx first.
    4. If httpx result is too short (< 500 chars) → retry with Playwright.
    5. Record success/failure to circuit breaker.

    Args:
        httpx_fetcher: The httpx-based fetcher.
        playwright_fetcher: The Playwright-based fetcher.
        rate_limiter: Optional rate limiter for per-host delays.
        circuit_breaker_enabled: Whether to enable circuit breaker protection.
        circuit_breaker_threshold: Consecutive failures before opening circuit.
        circuit_breaker_timeout: Cooldown period in seconds before retry.
    """

    def __init__(
        self,
        httpx_fetcher: HttpxFetcher,
        playwright_fetcher: PlaywrightFetcher,
        rate_limiter: HostRateLimiter | None = None,
        circuit_breaker_enabled: bool = True,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
        url_validation_enabled: bool = True,
    ) -> None:
        self._httpx = httpx_fetcher
        self._playwright = playwright_fetcher
        self._rate_limiter = rate_limiter
        self._circuit_breaker_enabled = circuit_breaker_enabled
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_timeout = circuit_breaker_timeout
        self._url_validation_enabled = url_validation_enabled
        self._url_validator = URLValidator() if url_validation_enabled else None
        self._breakers: dict[str, CircuitBreaker] = {}

    def _get_breaker(self, host: str) -> CircuitBreaker:
        """Get or create a circuit breaker for the given host.

        Args:
            host: The host name to get a breaker for.

        Returns:
            CircuitBreaker instance for the host.
        """
        if host not in self._breakers:
            self._breakers[host] = CircuitBreaker(
                threshold=self._circuit_breaker_threshold,
                timeout_secs=self._circuit_breaker_timeout,
            )
        return self._breakers[host]

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch URL using the best strategy.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.

        Returns:
            Tuple of (status_code, HTML content, response_headers).

        Raises:
            CircuitOpenError: If circuit breaker is open for the host.
            URLValidationError: If URL is blocked for security reasons.
        """
        # Validate URL for SSRF protection
        if self._url_validator:
            await self._url_validator.validate(url)

        host = urlparse(url).netloc

        # Check circuit breaker first
        if self._circuit_breaker_enabled:
            breaker = self._get_breaker(host)
            if await breaker.is_open():
                log.warning("circuit_breaker_open", url=url, host=host)
                raise CircuitOpenError(host)

        # Rate limiting
        if self._rate_limiter:
            await self._rate_limiter.acquire(url)

        # Execute fetch with circuit breaker tracking
        try:
            result = await self._do_fetch(url, headers, host)
            if self._circuit_breaker_enabled:
                await self._get_breaker(host).record_success()
            return result
        except CircuitOpenError:
            raise  # Don't record failure for circuit open
        except Exception as exc:
            if self._circuit_breaker_enabled:
                await self._get_breaker(host).record_failure()
            raise

    async def _do_fetch(
        self, url: str, headers: dict[str, str] | None, host: str
    ) -> tuple[int, str, dict[str, str]]:
        """Implement internal fetch logic without circuit breaker concerns.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers.
            host: Parsed host name.

        Returns:
            Tuple of (status_code, HTML content, response_headers).
        """
        if any(js_host in host for js_host in JS_REQUIRED_HOSTS):
            log.debug("smart_fetch_playwright_direct", url=url, host=host)
            return await self._playwright.fetch(url, headers)

        try:
            status, content, resp_headers = await self._httpx.fetch(url, headers)
            if status == 200 and len(content) >= MIN_CONTENT_LENGTH:
                return status, content, resp_headers

            log.debug(
                "smart_fetch_httpx_insufficient",
                url=url,
                content_len=len(content),
            )
        except Exception as exc:
            log.debug("smart_fetch_httpx_failed", url=url, error=str(exc))

        log.debug("smart_fetch_fallback_playwright", url=url)
        return await self._playwright.fetch(url, headers)

    async def close(self) -> None:
        """Close underlying fetchers."""
        await self._httpx.close()
        await self._playwright.close()
