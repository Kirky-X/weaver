"""Smart fetcher that chooses between httpx and Playwright based on response."""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.fetcher.base import BaseFetcher
from modules.fetcher.httpx_fetcher import HttpxFetcher
from modules.fetcher.playwright_fetcher import PlaywrightFetcher
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from modules.fetcher.rate_limiter import HostRateLimiter

log = get_logger("smart_fetcher")

# Hosts that are known to require JavaScript rendering
JS_REQUIRED_HOSTS: set[str] = {
    "weibo.com",
    "m.weibo.cn",
    "mp.weixin.qq.com",
    "toutiao.com",
}

# Minimum content length to consider a page valid
MIN_CONTENT_LENGTH = 500


class SmartFetcher(BaseFetcher):
    """Intelligent fetcher that tries httpx first, falls back to Playwright.

    Strategy:
    1. If host is known to need JS → use Playwright directly.
    2. Otherwise → try httpx first.
    3. If httpx result is too short (< 500 chars) → retry with Playwright.

    Args:
        httpx_fetcher: The httpx-based fetcher.
        playwright_fetcher: The Playwright-based fetcher.
        rate_limiter: Optional rate limiter for per-host delays.
    """

    def __init__(
        self,
        httpx_fetcher: HttpxFetcher,
        playwright_fetcher: PlaywrightFetcher,
        rate_limiter: HostRateLimiter | None = None,
    ) -> None:
        self._httpx = httpx_fetcher
        self._playwright = playwright_fetcher
        self._rate_limiter = rate_limiter

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch URL using the best strategy.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers to include in the request.

        Returns:
            Tuple of (status_code, HTML content, response_headers).
        """
        from urllib.parse import urlparse

        if self._rate_limiter:
            await self._rate_limiter.acquire(url)

        host = urlparse(url).netloc

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
