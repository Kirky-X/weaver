# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""BingSearcher — web search backend that reuses BaseFetcher for HTTP.

Architecture:
    - ``__init__`` stores a ``BaseFetcher`` instance (typically the project's
      ``HttpxFetcher`` singleton owned by ``SmartFetcher``) plus a
      ``BingSettings``-compatible config object and an optional
      ``QueryExpanderProtocol`` instance for LLM-driven query expansion.
    - ``search()`` builds the cn.bing.com search URL(s), calls
      ``fetcher.fetch(url, headers)`` in parallel for general + news verticals
      when ``mode`` requires it, and returns merged + deduplicated parsed
      results.
    - ``close()`` is intentionally a no-op — the fetcher is container-managed
      and shared with the ingestion pipeline; closing it here would break
      in-flight ingestion requests.

TDD stage (R-web-search-008 refactor):
    ``search()`` now accepts ``mode`` and ``time_filter`` so callers can
    request news-biased results (``mode="news"`` / ``mode="all"``) and
    time-filtered results (``time_filter="day"|"week"|"month"``). When
    the caller omits both, the implementation falls back to its
    configured defaults (``settings.news_enabled``, ``settings.time_filter``)
    so legacy callers continue to work. An optional ``query_expander``
    rewrites broad queries (e.g. "菲律宾" → ["菲律宾 仁爱礁",
    "菲律宾 南海"]) so Bing surfaces topical news rather than encyclopedic
    overviews.

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
    - ``parse_bing_html`` / ``parse_bing_news_html`` are synchronous
      CPU-bound functions (BeautifulSoup with the pure-Python
      ``html.parser`` backend). Following the project convention used by
      ``DuckDBPool``, ``gliner_extractor``, ``entity_extractor``, and
      ``hybrid_search``, they are wrapped in ``asyncio.to_thread`` to
      avoid blocking the event loop on the user request path.
    - When ``mode="all"`` (or ``mode="auto"`` with ``news_enabled=True``),
      general and news searches run in parallel via ``asyncio.gather``;
      results are merged + deduplicated by URL.
    - When query expansion is enabled, the original query plus each
      expanded query are searched in parallel; results merged + deduped.
    - An in-process TTL cache (``cachetools.TTLCache``) deduplicates
      repeated queries (e.g. trending topics) to save bandwidth and
      avoid Bing rate-limiting. Cache key is
      ``(query, effective_max, resolved_mode, effective_time_filter)``
      so callers with different ``mode`` / ``time_filter`` preferences
      get distinct entries.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from cachetools import TTLCache

from core.observability import get_logger
from modules.search.web.html_parser import parse_bing_html, parse_bing_news_html
from modules.search.web.protocol import (
    BingSearchMode,
    BingSearchResult,
    BingTimeFilter,
    QueryExpanderProtocol,
)

if TYPE_CHECKING:
    from modules.ingestion.fetching.base import BaseFetcher


log = get_logger(__name__)

_BING_SEARCH_URL = "https://cn.bing.com/search"
_BING_NEWS_SEARCH_URL = "https://cn.bing.com/news/search"
_DEFAULT_QUERY_LOG_PREFIX = 50
_MAX_QUERY_LEN = 500  # Bing accepts ~2KB URL; cap query at 500 chars to leave room for encoding
# Default cache capacity (entries). Tuned for trending-topic working set
# (a few hundred distinct queries per 30-minute TTL window).
_DEFAULT_CACHE_MAX_SIZE = 128

# Bing time filter windows: maps filter name → (seconds, days) tuple.
# Bing syntax: filters=ex1:"ez5_<seconds>_<days>". For example, week filter
# is ez5_604800_7 (604800 seconds = 7 days).
_TIME_FILTER_WINDOWS: dict[str, tuple[int, int]] = {
    "day": (86400, 1),  # 1 day
    "week": (604800, 7),  # 7 days
    "month": (2592000, 30),  # 30 days
}


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
            ``cache_ttl_seconds``, ``news_enabled``, ``news_max_results``,
            ``time_filter``, ``query_expansion_enabled``,
            ``query_expansion_max_terms``, ``query_expansion_timeout``).
            ``enabled`` is checked by the container, not here. Missing
            attributes default via ``getattr(..., default)`` so legacy
            settings objects (without the R-web-search-008 fields)
            continue to work — news_enabled defaults to False, time_filter
            to "none", query_expansion_enabled to False.
        cache: Optional pre-built TTL cache instance (for tests that need
            to inject a custom cache). When ``None`` (default), the
            searcher builds one from ``settings.cache_ttl_seconds`` —
            ``> 0`` enables caching with that TTL, ``0`` disables it.
        query_expander: Optional ``QueryExpanderProtocol`` instance for
            LLM-driven query expansion. When ``None`` (default) or when
            ``settings.query_expansion_enabled`` is False, no expansion
            happens. Lifecycle is owned by the DI container.
    """

    def __init__(
        self,
        fetcher: BaseFetcher,
        settings: Any,
        cache: TTLCache | None = None,
        query_expander: QueryExpanderProtocol | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._settings = settings
        self._query_expander = query_expander
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
        *,
        mode: BingSearchMode = "auto",
        time_filter: BingTimeFilter | None = None,
    ) -> list[BingSearchResult]:
        """Search Bing for ``query`` and return up to ``max_results`` hits.

        Args:
            query: Search query. Empty / whitespace-only queries return ``[]``
                without an HTTP call (defense-in-depth, even though callers
                should pre-validate). Queries > 500 chars are truncated.
            max_results: Upper bound on returned results. Applied AFTER
                merge + dedup. ``None`` (default) falls back to
                ``settings.max_results`` so the effective cap is configured
                in one place (DRY).
            mode: Search vertical selector (R-web-search-008). ``"auto"``
                (default) defers to ``settings.news_enabled`` — when news is
                enabled, both general and news verticals are queried and
                results merged + deduplicated. ``"general"`` queries only
                ``cn.bing.com/search``. ``"news"`` queries only
                ``cn.bing.com/news/search``. ``"all"`` queries both
                regardless of settings.
            time_filter: Time-range filter applied to the general search
                URL only (news is already time-sorted). ``None`` (default)
                defers to ``settings.time_filter``. ``"none"`` disables
                filtering (legacy behavior).

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

        # Resolve effective mode (R-web-search-008). "auto" defers to
        # settings.news_enabled so legacy callers without explicit mode
        # get news-biased results when news is configured.
        if mode == "auto":
            news_enabled = bool(getattr(self._settings, "news_enabled", False))
            resolved_mode: BingSearchMode = "all" if news_enabled else "general"
        else:
            resolved_mode = mode

        # Resolve effective time_filter (None → settings default).
        effective_time_filter: BingTimeFilter = (
            time_filter
            if time_filter is not None
            else getattr(self._settings, "time_filter", "none")
        )

        # Cache lookup: a hit avoids the HTTP round-trip and HTML parse.
        # Key includes (query, effective_max, resolved_mode,
        # effective_time_filter) so callers with different mode /
        # time_filter preferences get distinct entries.
        cache_key = (query, effective_max, resolved_mode, effective_time_filter)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.info(
                    "bing_search_cache_hit",
                    query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                    max_results=effective_max,
                    mode=resolved_mode,
                    time_filter=effective_time_filter,
                    result_count=len(cached),
                )
                return list(cached)  # copy to prevent caller mutation of cache entry

        # Query expansion (R-web-search-008). When enabled and an expander
        # is injected, broaden the original query into topical variants.
        # Failures (timeout, exception, empty result) fall back to the
        # original query only — search() MUST NOT raise on expansion failure.
        queries = await self._expand_query(query)

        # Run sub-searches in parallel. For each query, run general and/or
        # news search based on resolved_mode. Results are gathered via
        # asyncio.gather with return_exceptions=True so a single failure
        # doesn't sink the whole batch.
        tasks: list[asyncio.Future] = []
        for q in queries:
            if resolved_mode in ("general", "all"):
                tasks.append(
                    asyncio.ensure_future(
                        self._search_general(q, effective_max, effective_time_filter)
                    )
                )
            if resolved_mode in ("news", "all"):
                news_max = min(
                    int(getattr(self._settings, "news_max_results", effective_max)),
                    effective_max,
                )
                tasks.append(asyncio.ensure_future(self._search_news(q, news_max)))

        if not tasks:
            return []

        # H-1 fix: overall batch timeout prevents HostRateLimiter
        # serialization from causing unbounded waits. Per-search timeout
        # (settings.timeout) applies to each sub-search; the batch timeout
        # (2× per-search) bounds the total wall clock. On batch timeout,
        # degrade to [] (Rule 12 — Bing is a fallback path, never blocks).
        batch_timeout = float(getattr(self._settings, "timeout", 15)) * 2
        try:
            sub_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=batch_timeout,
            )
        except TimeoutError:
            log.warning(
                "bing_search_batch_timeout",
                query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                task_count=len(tasks),
                timeout=batch_timeout,
            )
            sub_results = []

        # Merge + deduplicate by URL (preserve first-seen order). Truncate
        # to effective_max AFTER dedup so duplicates don't consume the cap.
        merged: list[BingSearchResult] = []
        seen_urls: set[str] = set()
        for sub in sub_results:
            if isinstance(sub, Exception):
                log.warning(
                    "bing_search_subtask_failed",
                    query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                    error=str(sub),
                )
                continue
            if not isinstance(sub, list):
                continue
            for r in sub:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                merged.append(r)
                if len(merged) >= effective_max:
                    break
            if len(merged) >= effective_max:
                break

        log.info(
            "bing_search_completed",
            query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
            result_count=len(merged),
            max_results=effective_max,
            mode=resolved_mode,
            time_filter=effective_time_filter,
            expanded_queries=len(queries) - 1,
        )

        # Best-effort cache write: failures must NOT block the search flow
        # (Rule 12 — failures explicit, but a cache write error is non-fatal
        # because the caller already has the correct result).
        if self._cache is not None:
            try:
                self._cache[cache_key] = merged
            except Exception as cache_exc:
                log.warning(
                    "bing_search_cache_write_failed",
                    query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                    error=str(cache_exc),
                )

        return merged

    async def _expand_query(self, query: str) -> list[str]:
        """Run query expansion when enabled; fall back to [query] on failure.

        Returns a list of queries to search: [original_query] + expanded.
        When expansion is disabled, no expander is injected, or the
        expander fails/returns empty, returns [query].
        """
        if not getattr(self._settings, "query_expansion_enabled", False):
            return [query]
        if self._query_expander is None:
            return [query]

        max_terms = int(getattr(self._settings, "query_expansion_max_terms", 3))
        timeout = float(getattr(self._settings, "query_expansion_timeout", 5.0))

        try:
            expanded = await asyncio.wait_for(
                self._query_expander.expand(query, max_terms=max_terms),
                timeout=timeout,
            )
        except TimeoutError:
            log.warning(
                "query_expansion_timeout",
                query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                timeout=timeout,
            )
            return [query]
        except Exception as exc:
            log.warning(
                "query_expansion_failed",
                query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                error=str(exc),
            )
            return [query]

        if not expanded:
            return [query]

        # Original first (priority ordering), then expanded variants.
        # Deduplication happens at merge time by URL, not by query string,
        # because two different queries can surface the same article.
        # Apply _MAX_QUERY_LEN to each expanded term (defense in depth —
        # LLM may return long strings exceeding Bing's URL limit).
        truncated = [t[:_MAX_QUERY_LEN] for t in expanded]
        return [query] + truncated

    async def _search_general(
        self,
        query: str,
        max_results: int,
        time_filter: BingTimeFilter,
    ) -> list[BingSearchResult]:
        """Run a single Bing general search (cn.bing.com/search).

        Applies time_filter to the URL via ``filters=ex1:"ez5_<window>"``
        when time_filter != "none". Returns [] on HTTP error / non-200 /
        parse failure (per R-web-search-005 — never raise).
        """
        # Build URL: https://cn.bing.com/search?q=<quoted>&first=1[&filters=...]
        # ``first`` is 1-indexed offset (Bing convention). safe='' encodes
        # '/' to %2F to prevent path-separator interpretation in query value.
        url = f"{_BING_SEARCH_URL}?q={quote(query, safe='')}&first=1"
        if time_filter != "none":
            seconds, days = _TIME_FILTER_WINDOWS[time_filter]
            # Bing syntax: filters=ex1:"ez5_<seconds>_<days>"
            # quote with safe='' encodes ':' → %3A, '"' → %22
            filter_value = f'ex1:"ez5_{seconds}_{days}"'
            url += f"&filters={quote(filter_value, safe='')}"

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
                vertical="general",
            )
            return []
        except Exception as exc:
            log.warning(
                "bing_search_fetch_failed",
                query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                error=str(exc),
                vertical="general",
            )
            return []

        if status != 200 or not html:
            log.info(
                "bing_search_non_200_or_empty",
                status=status,
                html_len=len(html) if html else 0,
                vertical="general",
            )
            return []

        # CPU-bound HTML parsing off the event loop.
        results = await asyncio.to_thread(parse_bing_html, html, max_results=max_results)
        return results

    async def _search_news(
        self,
        query: str,
        max_results: int,
    ) -> list[BingSearchResult]:
        """Run a single Bing News vertical search (cn.bing.com/news/search).

        News search does NOT apply time_filter because the news vertical
        is already time-sorted by recency. Returns [] on HTTP error /
        non-200 / parse failure (per R-web-search-005 — never raise).
        """
        url = f"{_BING_NEWS_SEARCH_URL}?q={quote(query, safe='')}&first=1"
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
                vertical="news",
            )
            return []
        except Exception as exc:
            log.warning(
                "bing_search_fetch_failed",
                query_prefix=query[:_DEFAULT_QUERY_LOG_PREFIX],
                error=str(exc),
                vertical="news",
            )
            return []

        if status != 200 or not html:
            log.info(
                "bing_search_non_200_or_empty",
                status=status,
                html_len=len(html) if html else 0,
                vertical="news",
            )
            return []

        # News vertical HTML uses div.newsitem > a.title structure, with
        # li.b_algo cards as fallback. parse_bing_news_html handles both.
        results = await asyncio.to_thread(parse_bing_news_html, html, max_results=max_results)
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
