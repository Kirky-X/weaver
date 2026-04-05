# Copyright (c) 2026 KirkyX. All Rights Reserved
"""crawl4ai-based fetcher for JavaScript-rendered pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector
from modules.ingestion.fetching.base import BaseFetcher

if TYPE_CHECKING:
    from crawl4ai import AsyncWebCrawler

log = get_logger("crawl4ai_fetcher")


class Crawl4AIFetcher(BaseFetcher):
    """Fetcher using crawl4ai for JavaScript-rendered pages.

    Uses crawl4ai's AsyncWebCrawler with stealth mode to fetch
    pages that require JavaScript rendering.

    Args:
        headless: Run browser in headless mode (default True).
        stealth_enabled: Enable stealth mode to avoid bot detection.
        user_agent: Custom User-Agent string.
        timeout: Page load timeout in seconds.
    """

    def __init__(
        self,
        headless: bool = True,
        stealth_enabled: bool = True,
        user_agent: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._headless = headless
        self._stealth_enabled = stealth_enabled
        self._user_agent = user_agent
        self._timeout = timeout
        self._crawler: AsyncWebCrawler | None = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazy initialization of the crawler."""
        if self._initialized:
            return

        from crawl4ai import AsyncWebCrawler, BrowserConfig

        config = BrowserConfig(
            headless=self._headless,
            verbose=False,
            user_agent=self._user_agent,
        )

        if self._stealth_enabled:
            config.extra_args = {"enable_stealth": True}

        self._crawler = AsyncWebCrawler(config=config)
        await self._crawler.start()
        self._initialized = True
        log.info(
            "crawl4ai_initialized",
            headless=self._headless,
            stealth=self._stealth_enabled,
        )

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch content via crawl4ai.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers (note: crawl4ai has limited header support).

        Returns:
            Tuple of (status_code, html_content, response_headers).

        Raises:
            RuntimeError: If crawler initialization fails.
            Exception: If crawl fails.
        """
        import time

        await self._ensure_initialized()

        if not self._crawler:
            raise RuntimeError("Crawler not initialized")

        start = time.monotonic()
        try:
            result = await self._crawler.arun(url=url)

            if not result.success:
                raise RuntimeError(f"Crawl failed: {result.error_message or 'Unknown error'}")

            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="crawl4ai", status="success").inc()
            MetricsCollector.fetch_latency.labels(method="crawl4ai").observe(latency)

            log.debug(
                "crawl4ai_fetch_ok",
                url=url,
                status_code=result.status_code,
                latency_ms=int(latency * 1000),
            )

            response_headers = {}
            if hasattr(result, "response_headers") and result.response_headers:
                response_headers = dict(result.response_headers)

            return result.status_code, result.html, response_headers

        except Exception as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(method="crawl4ai", status="error").inc()
            MetricsCollector.fetch_latency.labels(method="crawl4ai").observe(latency)
            log.warning("crawl4ai_fetch_error", url=url, error=str(exc))
            raise

    async def close(self) -> None:
        """Close the crawler and release resources."""
        if self._crawler and self._initialized:
            await self._crawler.close()
            self._initialized = False
            log.info("crawl4ai_closed")
