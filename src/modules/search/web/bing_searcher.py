# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""BingSearcher — web search backend that reuses BaseFetcher for HTTP.

Architecture:
    - ``__init__`` stores a ``BaseFetcher`` instance (typically the project's
      ``HttpxFetcher`` singleton owned by ``SmartFetcher``) plus a
      ``BingSettings``-compatible config object.
    - ``search()`` builds the cn.bing.com search URL, calls
      ``fetcher.fetch(url, headers)``, and returns parsed results.
    - ``close()`` is intentionally a no-op — the fetcher is container-managed
      and shared with the ingestion pipeline; closing it here would break
      in-flight ingestion requests.

TDD stage (T006 Refactor):
    ``search()`` now wires ``parse_bing_html`` to the fetched HTML and
    returns real ``BingSearchResult`` lists. ``max_results`` is propagated
    to the parser for client-side truncation (Bing's ``first`` param is
    kept at 1 to fetch the first organic page; deeper paging is out of
    scope for the fallback path).

Security:
    - No third-party HTTP library is imported. All requests flow through
      ``BaseFetcher``, which enforces URL safety (SSRF / PhishTank /
      URLhaus) inside ``HttpxFetcher``.
    - The Bing search URL is constructed from a fixed template with
      ``urllib.parse.quote`` for the query parameter; no f-string
      interpolation of untrusted input into the URL.
    - User-supplied ``query`` is never logged verbatim beyond a truncated
      prefix (default 50 chars) to avoid log injection.

Performance notes:
    - ``asyncio.wait_for`` wraps ``fetcher.fetch`` as a defensive timeout
      cap. ``HttpxFetcher`` already enforces its own internal timeout via
      ``httpx.AsyncClient(timeout=...)``; the outer cap exists to guard
      against fetcher implementations that don't propagate timeouts
      correctly (e.g., a future Crawl4AIFetcher). The outer timeout should
      be >= the fetcher's internal timeout to avoid preempting legitimate
      retries.
    - ``parse_bing_html`` is a synchronous CPU-bound function (BeautifulSoup
      with the pure-Python ``html.parser`` backend). Following the project
      convention used by ``DuckDBPool``, ``gliner_extractor``,
      ``entity_extractor``, and ``hybrid_search``, it is wrapped in
      ``asyncio.to_thread`` to avoid blocking the event loop on the user
      request path (``search_unified`` API). Typical 100KB Bing page parses
      in 30-80ms; under concurrent fallback triggers this would otherwise
      serialize all in-flight requests.
    - An in-process TTL cache (``cachetools.TTLCache``) deduplicates
      repeated queries (e.g. trending topics) to save bandwidth and
      avoid Bing rate-limiting. Cache key is ``(query, effective_max)``
      so callers with different ``max_results`` preferences get distinct
      entries. Cache write failures are non-fatal (logged + search
      continues). TTL is configurable via ``settings.cache_ttl_seconds``
      (default 30 minutes; ``0`` disables caching).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from cachetools import TTLCache

from core.observability import get_logger
from modules.search.web.html_parser import parse_bing_html
from modules.search.web.protocol import BingSearchResult

if TYPE_CHECKING:
    from modules.ingestion.fetching.base import BaseFetcher


log = get_logger(__name__)

_BING_SEARCH_URL = "https://cn.bing.com/search"
_DEFAULT_QUERY_LOG_PREFIX = 50
_MAX_QUERY_LEN = 500  # Bing accepts ~2KB URL; cap query at 500 chars to leave room for encoding
# Default cache capacity (entries). Tuned for trending-topic working set
# (a few hundred distinct queries per 30-minute TTL window).
_DEFAULT_CACHE_MAX_SIZE = 128


class BingSearcher:
    """Bing HTML search backend.

    Implements ``BingSearchProtocol`` by delegating HTTP I/O to a
    ``BaseFetcher`` instance. See ``core.protocols.web_search`` for the
    protocol contract.

    Implements:
        - core.protocols.web_search.BingSearchProtocol

    Args:
        fetcher: ``BaseFetcher`` implementation (typically the project's
            shared ``HttpxFetcher``). Lifecycle is owned by the caller
            (DI container) — ``close()`` is a no-op per the protocol
            contract; the container closes the fetcher itself.
        settings: ``BingSettings`` (or duck-typed object exposing the
            attributes ``max_results``, ``timeout``, ``user_agent``,
            ``cache_ttl_seconds``). ``enabled`` is checked by the
            container, not here.
        cache: Optional pre-built TTL cache instance (for tests that need
            to inject a custom cache). When ``None`` (default), the
            searcher builds one from ``settings.cache_ttl_seconds`` —
            ``> 0`` enables caching with that TTL, ``0`` disables it.
    """

    def __init__(
        self,
        fetcher: BaseFetcher,
        settings: Any,
        cache: TTLCache | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._settings = settings
        # Cache injection point: when caller passes a cache, use it as-is
        # (tests inject a real TTLCache with a short TTL to verify expiry).
        # Otherwise build from settings — None means caching is disabled.
        if cache is not None:
            self._cache: TTLCache | None = cache
        elif getattr(settings, "cache_ttl_seconds", 0) > 0:
            self._cache = TTLCache(
                maxsize=_DEFAULT_CACHE_MAX_SIZE,
                ttl=settings.cache_ttl_seconds,
            )
        else:
            self._cache = None

    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> list[BingSearchResult]:
        """Search Bing for ``query`` and return up to ``max_results`` hits.

        Args:
            query: Search query. Empty / whitespace-only queries return ``[]``
                without an HTTP call (defense-in-depth, even though callers
                should pre-validate). Queries > 500 chars are truncated.
            max_results: Upper bound on returned results. Propagated to
                ``parse_bing_html`` for client-side truncation. ``None``
                (default) falls back to ``settings.max_results`` so the
                effective cap is configured in one place (DRY).

        Returns:
            List of ``BingSearchResult``. Empty on HTTP error, non-200
            status, empty body, or parse failure — see R-web-search-005
            (Bing must never block the main search flow).
        """
        # Defense-in-depth: validate query before constructing URL.
        if not query or not query.strip():
            return []
        if len(query) > _MAX_QUERY_LEN:
            query = query[:_MAX_QUERY_LEN]

        # DRY: resolve effective max_results from settings when caller omits.
        effective_max = max_results if max_results is not None else self._settings.max_results

        # Cache lookup: a hit avoids the HTTP round-trip and HTML parse.
        # Key includes effective_max so callers with different caps get
        # distinct entries (parsed lists are already client-truncated).
        cache_key = (query, effective_max)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.info(
                    "bing_search_cache_hit",
                    query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                    max_results=effective_max,
                    result_count=len(cached),
                )
                return list(cached)  # copy to prevent caller mutation of cache entry

        # Build URL: https://cn.bing.com/search?q=<quoted>&first=1
        # ``first`` is 1-indexed offset (Bing convention). safe='' encodes
        # '/' to %2F to prevent path-separator interpretation in query value.
        url = f"{_BING_SEARCH_URL}?q={quote(query, safe='')}&first=1"
        headers = {"User-Agent": self._settings.user_agent}

        try:
            status, html, _resp_headers = await asyncio.wait_for(
                self._fetcher.fetch(url, headers),
                timeout=self._settings.timeout,
            )
        except TimeoutError:
            log.warning(
                "bing_search_timeout",
                query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                timeout=self._settings.timeout,
            )
            return []
        except Exception as exc:
            log.warning(
                "bing_search_fetch_failed",
                query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                error=str(exc),
            )
            return []

        if status != 200 or not html:
            log.info(
                "bing_search_non_200_or_empty",
                status=status,
                html_len=len(html) if html else 0,
            )
            return []

        # CPU-bound HTML parsing off the event loop (project convention:
        # DuckDBPool / gliner_extractor / entity_extractor / hybrid_search
        # all wrap sync CPU work in asyncio.to_thread).
        results = await asyncio.to_thread(parse_bing_html, html, max_results=effective_max)
        log.info(
            "bing_search_completed",
            query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
            result_count=len(results),
            max_results=effective_max,
        )

        # Best-effort cache write: failures must NOT block the search flow
        # (Rule 12 — failures explicit, but a cache write error is non-fatal
        # because the caller already has the correct result).
        if self._cache is not None:
            try:
                self._cache[cache_key] = results
            except Exception as cache_exc:
                log.warning(
                    "bing_search_cache_write_failed",
                    query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                    error=str(cache_exc),
                )

        return results

    async def close(self) -> None:
        """No-op — the fetcher is container-managed and shared.

        Per ``BingSearchProtocol`` contract: container-managed fetchers are
        NOT closed here. ``SmartFetcher`` owns the ``HttpxFetcher``
        lifecycle and closes it during container shutdown. Calling
        ``fetcher.close()`` here would destroy the shared HTTP connection
        pool and break in-flight ingestion requests.

        This method exists for protocol symmetry and is safe to call
        multiple times.
        """
        # Intentionally empty. See class docstring for rationale.
        return
