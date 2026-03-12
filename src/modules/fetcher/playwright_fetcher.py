"""Playwright-based fetcher for JavaScript-heavy pages and anti-bot scenarios."""

from __future__ import annotations

from core.fetcher.playwright_pool import PlaywrightContextPool
from modules.fetcher.base import BaseFetcher
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector

log = get_logger("playwright_fetcher")


class PlaywrightFetcher(BaseFetcher):
    """Fetcher using Playwright for pages requiring JavaScript rendering.

    Args:
        pool: Playwright context pool for browser access.
    """

    def __init__(self, pool: PlaywrightContextPool) -> None:
        self._pool = pool

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch content via Playwright headless browser.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers (note: limited support in Playwright).

        Returns:
            Tuple of (status_code, page_content_html, response_headers).
        """
        import time

        start = time.monotonic()
        try:
            async with self._pool.acquire() as ctx:
                page = await ctx.new_page()
                try:
                    if headers:
                        await page.set_extra_http_headers(headers)
                    response = await page.goto(
                        url,
                        wait_until="networkidle",
                        timeout=30000,
                    )
                    status = response.status if response else 200
                    content = await page.content()
                    response_headers = dict(response.headers) if response else {}
                finally:
                    await page.close()

            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(
                method="playwright", status="success"
            ).inc()
            MetricsCollector.fetch_latency.labels(method="playwright").observe(latency)
            log.debug("playwright_fetch_ok", url=url, status=status)
            return status, content, response_headers
        except Exception as exc:
            latency = time.monotonic() - start
            MetricsCollector.fetch_total.labels(
                method="playwright", status="error"
            ).inc()
            MetricsCollector.fetch_latency.labels(method="playwright").observe(latency)
            log.warning("playwright_fetch_error", url=url, error=str(exc))
            raise

    async def close(self) -> None:
        """Nothing to close — pool is managed externally."""
        pass
