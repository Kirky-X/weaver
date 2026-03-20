# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Crawler with per-host and global concurrency control."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import trafilatura

from core.observability.logging import get_logger
from modules.collector.models import ArticleRaw
from modules.fetcher.base import BaseFetcher
from modules.fetcher.exceptions import FetchError
from modules.source.models import NewsItem

log = get_logger("crawler")

GLOBAL_MAX_CONCURRENCY = 32


class Crawler:
    """Concurrent web crawler with per-host rate limiting.

    Controls concurrency at two levels:
    - Global semaphore: min(cpu_count, host_count, 32)
    - Per-host semaphore: configurable per host (default: 2)

    Args:
        smart_fetcher: SmartFetcher instance for page retrieval.
        default_per_host: Default per-host concurrency limit.
    """

    def __init__(self, smart_fetcher: BaseFetcher, default_per_host: int = 2) -> None:
        self._fetcher = smart_fetcher
        self._default_per_host = default_per_host

    async def crawl_batch(
        self,
        items: list[NewsItem],
        per_host_config: dict[str, int] | None = None,
    ) -> list[ArticleRaw | FetchError]:
        """Crawl a batch of URLs concurrently.

        Args:
            items: List of NewsItem to crawl.
            per_host_config: Optional per-host concurrency overrides.

        Returns:
            List of ArticleRaw results or FetchError for failed items.
        """
        per_host_config = per_host_config or {}

        # Global concurrency = min(cpu, host_count, MAX)
        host_count = len({urlparse(i.url).netloc for i in items})
        global_limit = min(os.cpu_count() or 1, host_count, GLOBAL_MAX_CONCURRENCY)
        global_sem = asyncio.Semaphore(global_limit)

        # Per-host semaphores
        host_sems: dict[str, asyncio.Semaphore] = {}
        for item in items:
            host = urlparse(item.url).netloc
            if host not in host_sems:
                limit = per_host_config.get(host, self._default_per_host)
                host_sems[host] = asyncio.Semaphore(limit)

        async def crawl_one(item: NewsItem) -> ArticleRaw:
            host = urlparse(item.url).netloc
            async with global_sem, host_sems[host]:
                status, html, _ = await self._fetcher.fetch(item.url)
                body = trafilatura.extract(html, include_comments=False) or ""
                return ArticleRaw(
                    url=item.url,
                    title=item.title,
                    body=body,
                    source=item.source,
                    publish_time=item.pubDate,
                    source_host=host,
                )

        results = await asyncio.gather(
            *[crawl_one(i) for i in items],
            return_exceptions=True,
        )

        # Wrap non-FetchError exceptions with URL context
        wrapped_results: list[ArticleRaw | FetchError] = []
        for item, result in zip(items, results):
            if isinstance(result, FetchError):
                wrapped_results.append(result)
            elif isinstance(result, Exception):
                wrapped_results.append(
                    FetchError(
                        url=item.url,
                        message=str(result),
                        cause=result,
                    )
                )
            elif isinstance(result, ArticleRaw):
                wrapped_results.append(result)
            # else: BaseException (like KeyboardInterrupt) - skip

        # Log results
        successes = sum(1 for r in wrapped_results if isinstance(r, ArticleRaw))
        failures = sum(1 for r in wrapped_results if isinstance(r, FetchError))
        log.info(
            "crawl_batch_complete",
            total=len(items),
            successes=successes,
            failures=failures,
        )

        return wrapped_results
