# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Smart fetcher that chooses between httpx and crawl4ai based on response."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from core.observability.logging import get_logger
from core.resilience.circuit_breaker import CircuitBreaker
from modules.ingestion.fetching.base import BaseFetcher
from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher
from modules.ingestion.fetching.exceptions import CircuitOpenError
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

if TYPE_CHECKING:
    from core.security import URLValidator
    from modules.ingestion.fetching.rate_limiter import HostRateLimiter

log = get_logger("smart_fetcher")

# Minimum content length to consider a page valid
MIN_CONTENT_LENGTH = 500

# SPA detection patterns
SPA_ROOT_PATTERN = re.compile(
    r'<(?:div|section)\s+id=["\'](?:app|root)["\'][^>]*>\s*</(?:div|section)>', re.IGNORECASE
)
SPA_FRAMEWORK_PATTERNS = [
    re.compile(r"__NEXT_DATA__", re.IGNORECASE),
    re.compile(r"__NUXT__", re.IGNORECASE),
    re.compile(r"ng-version", re.IGNORECASE),
    re.compile(r"data-reactroot", re.IGNORECASE),
]


def _appears_to_be_spa(html: str) -> bool:
    """Detect if HTML appears to be a Single Page Application.

    Checks for:
    1. Empty root elements (id="app", id="root")
    2. Framework signatures (__NEXT_DATA__, __NUXT__, ng-version, data-reactroot)
    3. Script-heavy pages with minimal visible content

    Args:
        html: The HTML content to analyze.

    Returns:
        True if the page appears to be an SPA, False otherwise.
    """
    # Check for empty root elements
    if SPA_ROOT_PATTERN.search(html):
        return True

    # Check for framework signatures
    for pattern in SPA_FRAMEWORK_PATTERNS:
        if pattern.search(html):
            return True

    # Check for script-heavy low-content pages
    script_count = html.lower().count("<script")
    visible_text = re.sub(r"<[^>]+>", "", html)
    visible_text = re.sub(r"\s+", " ", visible_text).strip()

    # If many scripts but very little visible text, likely SPA
    return script_count > 5 and len(visible_text) < 200


class SmartFetcher(BaseFetcher):
    """Intelligent fetcher that tries httpx first, falls back to crawl4ai.

    Strategy:
    1. If force_browser=True → use crawl4ai directly.
    2. If circuit breaker is open for host → raise CircuitOpenError.
    3. Otherwise → try httpx first.
    4. If httpx result appears to be SPA → retry with crawl4ai.
    5. If httpx result is too short (< 500 chars) → retry with crawl4ai.
    6. Record success/failure to circuit breaker.

    Args:
        httpx_fetcher: The httpx-based fetcher.
        crawl4ai_fetcher: The crawl4ai-based fetcher for JS rendering.
        rate_limiter: Optional rate limiter for per-host delays.
        circuit_breaker_enabled: Whether to enable circuit breaker protection.
        circuit_breaker_threshold: Consecutive failures before opening circuit.
        circuit_breaker_timeout: Cooldown period in seconds before retry.
        url_validator: Optional URL validator for security checks.
    """

    def __init__(
        self,
        httpx_fetcher: HttpxFetcher,
        crawl4ai_fetcher: Crawl4AIFetcher,
        rate_limiter: HostRateLimiter | None = None,
        circuit_breaker_enabled: bool = True,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
        url_validator: URLValidator | None = None,
    ) -> None:
        self._httpx = httpx_fetcher
        self._crawl4ai = crawl4ai_fetcher
        self._rate_limiter = rate_limiter
        self._circuit_breaker_enabled = circuit_breaker_enabled
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_timeout = circuit_breaker_timeout
        self._url_validator = url_validator
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
        self,
        url: str,
        headers: dict[str, str] | None = None,
        force_browser: bool = False,
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch URL using the best strategy.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.
            force_browser: If True, skip httpx and use crawl4ai directly.

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
            result = await self._do_fetch(url, headers, host, force_browser)
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
        self,
        url: str,
        headers: dict[str, str] | None,
        host: str,
        force_browser: bool,
    ) -> tuple[int, str, dict[str, str]]:
        """Implement internal fetch logic without circuit breaker concerns.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers.
            host: Parsed host name.
            force_browser: If True, use crawl4ai directly.

        Returns:
            Tuple of (status_code, HTML content, response_headers).
        """
        # Force browser mode - skip httpx entirely
        if force_browser:
            log.debug("smart_fetch_crawl4ai_forced", url=url, host=host)
            return await self._crawl4ai.fetch(url, headers)

        try:
            status, content, resp_headers = await self._httpx.fetch(url, headers)
            if status == 200:
                # Check if response appears to be SPA
                if _appears_to_be_spa(content):
                    log.debug("smart_fetch_spa_detected", url=url, host=host)
                    return await self._crawl4ai.fetch(url, headers)

                # Check content length - if insufficient, fall back to crawl4ai
                if len(content) < MIN_CONTENT_LENGTH:
                    log.debug(
                        "smart_fetch_httpx_insufficient",
                        url=url,
                        content_len=len(content),
                    )
                    return await self._crawl4ai.fetch(url, headers)

                return status, content, resp_headers
            return status, content, resp_headers

        except Exception as exc:
            log.debug("smart_fetch_httpx_failed", url=url, error=str(exc))

        log.debug("smart_fetch_fallback_crawl4ai", url=url)
        return await self._crawl4ai.fetch(url, headers)

    async def close(self) -> None:
        """Close underlying fetchers."""
        await self._httpx.close()
        await self._crawl4ai.close()
