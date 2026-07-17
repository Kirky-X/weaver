# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Crawler with per-host and global concurrency control."""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import trafilatura

from core.observability import get_logger
from modules.ingestion.domain.models import NewsItem, RawArticle
from modules.ingestion.fetching.base import BaseFetcher
from modules.ingestion.fetching.exceptions import FetchError

if TYPE_CHECKING:
    from modules.ingestion.deduplication.retry import RetryQueue

log = get_logger(__name__)

GLOBAL_MAX_CONCURRENCY = 32

# Minimum article length for valid content
MIN_ARTICLE_LENGTH = 100

# Maximum total time for a single crawl_batch call (seconds)
MAX_CRAWL_BATCH_TIME = 300  # 5 minutes

# HTML title extraction patterns (ordered by priority)
_OG_TITLE_RE = re.compile(
    r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_TITLE_RE_REVERSED = re.compile(
    r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:title["\']',
    re.IGNORECASE,
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _extract_title_from_html(html: str) -> str | None:
    """Extract page title from HTML when trafilatura fails.

    Tries in order:
    1. <meta property="og:title" content="..."> (most reliable for news sites)
    2. <title>...</title> tag

    Args:
        html: Raw HTML content.

    Returns:
        Extracted title string, or None if no title found.

    """
    # 1. Try Open Graph title meta tag (preferred for news sites)
    match = _OG_TITLE_RE.search(html) or _OG_TITLE_RE_REVERSED.search(html)
    if match:
        title = match.group(1).strip()
        if title:
            return title

    # 2. Fall back to <title> tag
    match = _TITLE_TAG_RE.search(html)
    if match:
        title = match.group(1).strip()
        if title:
            return title

    return None


class Crawler:
    """Concurrent web crawler with per-host rate limiting.

    Controls concurrency at two levels:
    - Global semaphore: min(cpu_count, host_count, 32)
    - Per-host semaphore: configurable per host (default: 2)

    Args:
        smart_fetcher: SmartFetcher instance for page retrieval.
        default_per_host: Default per-host concurrency limit.
    """

    def __init__(
        self,
        smart_fetcher: BaseFetcher,
        default_per_host: int = 2,
        retry_queue: RetryQueue | None = None,
    ) -> None:
        self._fetcher = smart_fetcher
        self._default_per_host = default_per_host
        self._retry_queue = retry_queue

    async def _fetch_html(self, url: str, force_browser: bool = False) -> tuple[str | None, int]:
        """Fetch HTML with HTTP status validation.

        Returns (html, status_code). html is None when status >= 400 (error
        pages like 404/403 are not valid article content). This prevents
        error pages and login redirects from being persisted as articles
        (R1 fix — previously status_code was discarded with ``_``).

        Contract: on fetch exception or status >= 400, enqueues the URL
        to ``RetryQueue`` (if wired) for dead-letter retry, THEN
        re-raises so ``crawl_one`` propagates the failure to
        ``asyncio.gather(return_exceptions=True)``. Swallowing the
        exception here would cause ``crawl_one`` to return an empty
        ``RawArticle`` — silently masking the failure (pre-existing
        test regression fixed here). See ``temp/report.md`` D4.
        """
        try:
            status, html, _ = await self._fetcher.fetch(url, force_browser=force_browser)
        except Exception as exc:
            log.warning("crawler_fetch_error", url=url, error=str(exc))
            await self._enqueue_retry(url)
            raise

        if status >= 400:
            log.warning(
                "crawler_http_error_page_skipped",
                url=url,
                status=status,
            )
            await self._enqueue_retry(url)
            raise FetchError(
                url=url,
                message=f"HTTP {status} for {url}",
            )

        return html, status

    async def _enqueue_retry(self, url: str) -> None:
        """Enqueue URL to RetryQueue with host extracted from url (D4 fix).

        No-op when retry_queue is not wired (backward compat).
        """
        if self._retry_queue is None:
            return
        host = urlparse(url).netloc
        try:
            await self._retry_queue.enqueue(url, host, attempt=0)
        except Exception as exc:
            # Retry queue failure must not break the crawl flow
            log.warning("retry_queue_enqueue_failed", url=url, host=host, error=str(exc))

    async def crawl_batch(
        self,
        items: list[NewsItem],
        per_host_config: dict[str, int] | None = None,
    ) -> list[RawArticle | FetchError]:
        """Crawl a batch of URLs concurrently.

        Args:
            items: List of NewsItem to crawl.
            per_host_config: Optional per-host concurrency overrides.

        Returns:
            List of RawArticle results or FetchError for failed items.
        """
        per_host_config = per_host_config or {}

        # Validate per_host_config values
        for host, limit in per_host_config.items():
            if not isinstance(host, str):
                raise TypeError(f"Host key must be string, got {type(host).__name__}")
            if not isinstance(limit, int) or limit < 1:
                raise ValueError(
                    f"Invalid concurrency for {host}: {limit!r} (expected positive integer)"
                )

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

        async def crawl_one(item: NewsItem) -> RawArticle:
            host = urlparse(item.url).netloc
            body = ""
            html_content: str | None = None

            if item.body:
                # Body already extracted from content:encoded in the RSS feed.
                # Check if it's already plain text (no HTML tags) or HTML content.
                # RSSParser._strip_html_tags produces plain text, so we should
                # validate length directly instead of using trafilatura.extract().
                if len(item.body) >= MIN_ARTICLE_LENGTH:
                    # Already sufficient plain text content
                    body = item.body
                else:
                    # Body might be HTML (e.g., from other sources) or insufficient plain text.
                    # Try trafilatura for HTML content.
                    extracted = trafilatura.extract(item.body, include_comments=False)
                    if extracted and len(extracted) >= MIN_ARTICLE_LENGTH:
                        body = extracted
                    else:
                        log.debug(
                            "prefilled_body_insufficient",
                            url=item.url,
                            original_len=len(item.body),
                            extracted_len=len(extracted) if extracted else 0,
                        )
                        # Re-fetch with browser rendering
                        async with global_sem, host_sems[host]:
                            html, _ = await self._fetch_html(item.url, force_browser=True)
                            html_content = html
                            if html:
                                body = trafilatura.extract(html, include_comments=False) or ""
            else:
                # No pre-filled body, fetch the page
                async with global_sem, host_sems[host]:
                    html, _ = await self._fetch_html(item.url)
                    html_content = html
                    if html:
                        body = trafilatura.extract(html, include_comments=False) or ""

                if len(body) < MIN_ARTICLE_LENGTH:
                    log.debug(
                        "first_fetch_insufficient",
                        url=item.url,
                        content_len=len(body),
                    )
                    # Re-fetch with browser rendering
                    async with global_sem, host_sems[host]:
                        html, _ = await self._fetch_html(item.url, force_browser=True)
                        html_content = html
                        if html:
                            body = trafilatura.extract(html, include_comments=False) or ""

            # Extract title from HTML if not provided by RSS/source
            title = item.title
            if not title and html_content:
                # 1. Try trafilatura first (best quality when it works)
                try:
                    bare = trafilatura.bare_extraction(html_content, include_comments=False)
                    if bare and bare.title:
                        title = bare.title
                        log.debug(
                            "crawler_title_extracted_trafilatura",
                            url=item.url,
                            title=title[:50],
                        )
                except Exception as exc:
                    log.debug("crawler_title_trafilatura_failed", url=item.url, error=str(exc))

                # 2. Fallback: parse <meta og:title> or <title> tag from HTML
                #    trafilatura returns title=None for some sites (e.g. IT之家, Solidot)
                if not title:
                    extracted = _extract_title_from_html(html_content)
                    if extracted:
                        title = extracted
                        log.debug(
                            "crawler_title_extracted_html_tag",
                            url=item.url,
                            title=title[:50],
                        )

            return RawArticle(
                url=item.url,
                title=title,
                body=body,
                html=html_content,
                source=item.source,
                source_id=item.source_id,
                publish_time=item.publish_time,
                source_host=host,
                description=item.description or "",
            )

        start_time = time.monotonic()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[crawl_one(i) for i in items], return_exceptions=True),
                timeout=MAX_CRAWL_BATCH_TIME,
            )
        except TimeoutError:
            elapsed = time.monotonic() - start_time
            log.warning(
                "crawl_batch_timeout",
                elapsed=round(elapsed, 1),
                total=len(items),
            )
            # Return FetchError for all items on timeout
            return [
                FetchError(url=item.url, message=f"Batch timed out after {elapsed:.0f}s")
                for item in items
            ]

        # Wrap non-FetchError exceptions with URL context
        wrapped_results: list[RawArticle | FetchError] = []
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
            elif isinstance(result, RawArticle):
                wrapped_results.append(result)
            # else: BaseException (like KeyboardInterrupt) - skip

        successes = sum(1 for r in wrapped_results if isinstance(r, RawArticle))
        failures = sum(1 for r in wrapped_results if isinstance(r, FetchError))
        log.info(
            "crawl_batch_complete",
            total=len(items),
            successes=successes,
            failures=failures,
        )

        return wrapped_results
