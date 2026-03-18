# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Fetcher module - Web content fetching with Playwright and HTTPX."""

from modules.fetcher.base import BaseFetcher
from modules.fetcher.httpx_fetcher import HttpxFetcher
from modules.fetcher.playwright_fetcher import PlaywrightFetcher
from modules.fetcher.playwright_pool import PlaywrightContextPool
from modules.fetcher.rate_limiter import HostRateLimiter
from modules.fetcher.smart_fetcher import SmartFetcher

__all__ = [
    "BaseFetcher",
    "HostRateLimiter",
    "HttpxFetcher",
    "PlaywrightContextPool",
    "PlaywrightFetcher",
    "SmartFetcher",
]
