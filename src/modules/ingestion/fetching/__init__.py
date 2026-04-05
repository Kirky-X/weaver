# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Fetcher module - Web content fetching with crawl4ai and HTTPX.

This module provides:
- BaseFetcher: Abstract interface for all fetcher implementations
- HttpxFetcher: Lightweight HTTP client for simple requests
- Crawl4AIFetcher: Browser-based fetcher for JS-heavy pages
- SmartFetcher: Intelligent fetcher with automatic strategy selection
- CircuitOpenError: Raised when circuit breaker blocks requests
- FetchError: Unified fetch error with complete context
"""

from modules.ingestion.fetching.base import BaseFetcher
from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher
from modules.ingestion.fetching.exceptions import CircuitOpenError, FetchError
from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
from modules.ingestion.fetching.rate_limiter import HostRateLimiter
from modules.ingestion.fetching.smart_fetcher import SmartFetcher

__all__ = [
    "BaseFetcher",
    "CircuitOpenError",
    "Crawl4AIFetcher",
    "FetchError",
    "HostRateLimiter",
    "HttpxFetcher",
    "SmartFetcher",
]
