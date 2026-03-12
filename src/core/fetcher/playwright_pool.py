"""Playwright browser context pool for anti-bot scraping."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

from core.observability.logging import get_logger

log = get_logger("playwright_pool")


class PlaywrightContextPool:
    """Single Browser instance + N BrowserContext pool.

    Each context has isolated cookies/storage. Contexts are cleaned
    and returned to the pool after use.

    Args:
        pool_size: Number of browser contexts to maintain.
    """

    def __init__(self, pool_size: int = 5) -> None:
        self._pool_size = pool_size
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._pool: asyncio.Queue[BrowserContext] = asyncio.Queue()

    async def startup(self) -> None:
        """Launch browser and create context pool."""
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        for _ in range(self._pool_size):
            ctx = await self._browser.new_context(
                user_agent="Mozilla/5.0 (compatible; NewsBot/1.0)",
            )
            await self._pool.put(ctx)
        log.info("playwright_pool_started", pool_size=self._pool_size)

    async def shutdown(self) -> None:
        """Close all contexts, browser, and playwright."""
        while not self._pool.empty():
            ctx = await self._pool.get()
            await ctx.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        log.info("playwright_pool_closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[BrowserContext]:
        """Acquire a browser context from the pool.

        Yields:
            A BrowserContext for use.

        The context's cookies are cleared on return to prevent
        session pollution between requests.
        """
        ctx = await self._pool.get()
        try:
            yield ctx
        finally:
            await ctx.clear_cookies()
            await self._pool.put(ctx)
