"""Playwright-based fetcher for JavaScript-heavy pages and anti-bot scenarios."""

from __future__ import annotations

import asyncio
import random
import time

from core.fetcher.playwright_pool import PlaywrightContextPool
from modules.fetcher.base import BaseFetcher
from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector

log = get_logger("playwright_fetcher")


class PlaywrightFetcher(BaseFetcher):
    """Fetcher using Playwright for pages requiring JavaScript rendering.

    Args:
        pool: Playwright context pool for browser access.
        human_like_delay: Whether to add random delays to simulate human behavior.
    """

    def __init__(
        self,
        pool: PlaywrightContextPool,
        human_like_delay: bool = True,
    ) -> None:
        self._pool = pool
        self._human_like_delay = human_like_delay

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, str, dict[str, str]]:
        """Fetch content via Playwright headless browser with stealth.

        Args:
            url: The URL to fetch.
            headers: Optional HTTP headers (note: limited support in Playwright).

        Returns:
            Tuple of (status_code, page_content_html, response_headers).
        """
        start = time.monotonic()
        try:
            async with self._pool.acquire() as ctx:
                page = await ctx.new_page()
                try:
                    await self._pool.apply_stealth_to_page(page)

                    if headers:
                        await page.set_extra_http_headers(headers)

                    if self._human_like_delay:
                        await self._pool.random_delay()

                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )

                    if self._human_like_delay:
                        await self._wait_for_content(page)

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

    async def _wait_for_content(self, page) -> None:
        """Wait for page content to load with human-like behavior.

        This method simulates human reading behavior by:
        1. Waiting for network to settle
        2. Adding a small random delay
        3. Optionally scrolling slightly (triggers lazy-loaded content)
        """
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        await self._pool.random_delay()

        try:
            scroll_amount = random.randint(100, 300)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.evaluate(f"window.scrollBy(0, -{scroll_amount})")
        except Exception:
            pass

    async def close(self) -> None:
        """Nothing to close — pool is managed externally."""
        pass
