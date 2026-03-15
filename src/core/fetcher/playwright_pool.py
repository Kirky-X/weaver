"""Playwright browser context pool for anti-bot scraping."""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from playwright_stealth.stealth import Stealth

from core.observability.logging import get_logger

log = get_logger("playwright_pool")


class PlaywrightContextPool:
    """Single Browser instance + N BrowserContext pool with stealth support.

    Each context has isolated cookies/storage. Contexts are cleaned
    and returned to the pool after use.

    Args:
        pool_size: Number of browser contexts to maintain.
        stealth_enabled: Enable playwright-stealth anti-detection.
        user_agent: Custom user agent string.
        viewport_width: Viewport width in pixels.
        viewport_height: Viewport height in pixels.
        locale: Browser locale (e.g., "zh-CN").
        timezone: Browser timezone (e.g., "Asia/Shanghai").
        random_delay_min: Minimum random delay before actions (seconds).
        random_delay_max: Maximum random delay before actions (seconds).
    """

    def __init__(
        self,
        pool_size: int = 5,
        stealth_enabled: bool = True,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        locale: str = "zh-CN",
        timezone: str = "Asia/Shanghai",
        random_delay_min: float = 0.5,
        random_delay_max: float = 2.0,
    ) -> None:
        self._pool_size = pool_size
        self._stealth_enabled = stealth_enabled
        self._user_agent = user_agent
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        self._locale = locale
        self._timezone = timezone
        self._random_delay_min = random_delay_min
        self._random_delay_max = random_delay_max

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._pool: asyncio.Queue[BrowserContext] = asyncio.Queue()
        self._stealth = Stealth() if stealth_enabled else None

    async def startup(self) -> None:
        """Launch browser and create context pool with stealth configuration."""
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )

        for _ in range(self._pool_size):
            ctx = await self._create_stealth_context()
            await self._pool.put(ctx)

        log.info(
            "playwright_pool_started",
            pool_size=self._pool_size,
            stealth_enabled=self._stealth_enabled,
        )

    async def _create_stealth_context(self) -> BrowserContext:
        """Create a browser context with stealth configuration.

        Returns:
            Configured BrowserContext with anti-detection settings.
        """
        context = await self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": self._viewport_width, "height": self._viewport_height},
            locale=self._locale,
            timezone_id=self._timezone,
            color_scheme="light",
            has_touch=False,
            is_mobile=False,
            java_script_enabled=True,
            ignore_https_errors=True,
        )

        if self._stealth_enabled and self._stealth:
            await self._stealth.apply_stealth_async(context)

        return context

    async def apply_stealth_to_page(self, page: Page) -> None:
        """Apply stealth configuration to a specific page.

        This is useful when additional stealth measures are needed
        beyond the context-level configuration.

        Args:
            page: The Page instance to apply stealth to.
        """
        if self._stealth_enabled and self._stealth:
            await self._stealth.apply_stealth_async(page)

    async def random_delay(self) -> None:
        """Apply a random delay to simulate human behavior.

        The delay duration is between random_delay_min and random_delay_max.
        """
        if self._random_delay_min > 0 and self._random_delay_max > 0:
            delay = random.uniform(self._random_delay_min, self._random_delay_max)
            await asyncio.sleep(delay)

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
