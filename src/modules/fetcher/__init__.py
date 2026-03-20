# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Fetcher module - Web content fetching with Playwright and HTTPX.

This module provides:
- BaseFetcher: Abstract interface for all fetcher implementations
- HttpxFetcher: Lightweight HTTP client for simple requests
- PlaywrightFetcher: Browser-based fetcher for JS-heavy pages
- SmartFetcher: Intelligent fetcher with automatic strategy selection
- CircuitOpenError: Raised when circuit breaker blocks requests
- FetchError: Unified fetch error with complete context
"""

from modules.fetcher.base import BaseFetcher
from modules.fetcher.exceptions import CircuitOpenError, FetchError
from modules.fetcher.httpx_fetcher import HttpxFetcher
from modules.fetcher.playwright_fetcher import PlaywrightFetcher
from modules.fetcher.playwright_pool import PlaywrightContextPool
from modules.fetcher.rate_limiter import HostRateLimiter
from modules.fetcher.smart_fetcher import SmartFetcher

__all__ = [
    "BaseFetcher",
    "CircuitOpenError",
    "FetchError",
    "HostRateLimiter",
    "HttpxFetcher",
    "PlaywrightContextPool",
    "PlaywrightFetcher",
    "SmartFetcher",
]
