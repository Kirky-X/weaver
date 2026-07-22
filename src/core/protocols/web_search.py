# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Web search protocol — backend abstraction for external search engines.

Defines the abstract ``BingSearchProtocol`` that any web search backend
must implement, plus the immutable ``BingSearchResult`` dataclass returned
by searches. Concrete implementations live in ``modules.search.web``.

Although the protocol name carries "Bing" (historical, because Bing is the
first concrete backend), the interface itself is backend-agnostic — any
HTML-scraping or API-based search engine (Google, DuckDuckGo, etc.) can
implement it without modification. Future renames to
``WebSearchProtocol`` / ``WebSearchResult`` are tracked as a tech-debt item
to coordinate with downstream callers.

R-web-search-008 — news vertical + query expansion:
    ``search()`` accepts ``mode`` and ``time_filter`` so callers can request
    news-biased results (``mode="news"`` / ``mode="all"``) and time-filtered
    results (``time_filter="day"|"week"|"month"``). When the caller omits
    both, the implementation falls back to its configured defaults
    (``settings.news_enabled``, ``settings.time_filter``) so legacy
    callers continue to work.

    ``QueryExpanderProtocol`` abstracts LLM-driven query expansion so the
    searcher can be constructed without an expander (caching/legacy path)
    and have one injected at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# Search mode: which Bing vertical(s) to query. ``auto`` defers to the
# implementation's settings (BingSettings.news_enabled). R-web-search-008.
BingSearchMode = Literal["auto", "general", "news", "all"]

# Time filter window applied to general search URL. ``none`` = no filter.
# Maps to Bing ``filters=ex1:"ez5_<window>"`` syntax.
BingTimeFilter = Literal["none", "day", "week", "month"]


@dataclass(frozen=True)
class BingSearchResult:
    """Single web search result entry.

    Immutable so results can be safely shared across async tasks
    (e.g., when fanned out to background pipeline processing).

    Attributes:
        title: Result page title (plain text, HTML-stripped).
        url: Absolute result URL (already validated by BaseFetcher's
            URLValidator before being wrapped in this dataclass).
        snippet: Short excerpt shown under the title on the result page.
    """

    title: str
    url: str
    snippet: str


@runtime_checkable
class BingSearchProtocol(Protocol):
    """Protocol for web search backends used by the search fallback orchestrator.

    Implementations must be async and stateless across calls (no per-query
    mutable state). Lifecycle is managed by the DI container, which calls
    ``close()`` during shutdown.

    Known implementations:
        - :class:`modules.search.web.bing_searcher.BingSearcher`

    Note:
        Implementations MUST reuse ``BaseFetcher`` for HTTP requests —
        introducing third-party HTTP libraries (httpx/aiohttp/requests)
        directly is prohibited by the project's fetcher abstraction.

    Lifecycle contract:
        ``close()`` must NOT close container-managed fetchers. The container
        owns the fetcher's lifecycle (init/shutdown); concrete searchers
        that share the ingestion pipeline's ``HttpxFetcher`` singleton must
        treat ``close()`` as a no-op or only clean up searcher-local state.
    """

    async def search(
        self,
        query: str,
        max_results: int | None = None,
        *,
        mode: BingSearchMode = "auto",
        time_filter: BingTimeFilter | None = None,
    ) -> list[BingSearchResult]:
        """Search the web for ``query`` and return up to ``max_results`` hits.

        Args:
            query: Search query string (non-empty, caller-validated).
            max_results: Upper bound on returned results. Implementations
                may return fewer (including an empty list) when the backend
                yields fewer hits or fails gracefully. ``None`` (default)
                lets the implementation fall back to its configured
                ``settings.max_results`` so the effective cap is defined in
                one place (DRY) — see ``BingSearcher.search``.
            mode: Search vertical selector (R-web-search-008). ``"auto"``
                (default) defers to ``settings.news_enabled`` — when news is
                enabled, both general and news verticals are queried and
                results merged + deduplicated. ``"general"`` queries only
                ``cn.bing.com/search``. ``"news"`` queries only
                ``cn.bing.com/news/search``. ``"all"`` queries both
                regardless of settings.
            time_filter: Time-range filter applied to the general search
                URL. ``None`` (default) defers to ``settings.time_filter``.
                ``"none"`` disables filtering (legacy behavior).

        Returns:
            List of ``BingSearchResult`` objects, possibly empty on failure
            or no hits. Implementations MUST NOT raise on transient backend
            errors — log and return ``[]`` instead so the main search flow
            is never blocked.
        """
        ...

    async def close(self) -> None:
        """Release searcher-local resources.

        No-op for implementations that share a container-managed fetcher
        (the container closes the fetcher itself during shutdown). Safe to
        call multiple times.
        """
        ...


@runtime_checkable
class QueryExpanderProtocol(Protocol):
    """Protocol for LLM-driven query expansion (R-web-search-008).

    Broad user queries (e.g. "菲律宾") often fail to surface topical news
    because Bing returns encyclopedic overviews. The expander rewrites a
    broad query into ``max_terms`` focused variants (e.g.
    "菲律宾 仁爱礁", "菲律宾 南海") that the searcher then queries in
    parallel.

    Known implementations:
        - :class:`modules.search.web.query_expander.LLMQueryExpander`

    Lifecycle contract:
        Stateless across calls. Lifecycle is owned by the DI container;
        implementations that hold an LLM client reference treat it as
        read-only (the container owns the LLM client's lifecycle).
    """

    async def expand(
        self,
        query: str,
        *,
        max_terms: int = 3,
    ) -> list[str]:
        """Return up to ``max_terms`` expanded queries for ``query``.

        Args:
            query: Original user query (non-empty, caller-validated).
            max_terms: Upper bound on returned queries. Implementations
                may return fewer (including an empty list) on failure or
                when no meaningful expansion exists.

        Returns:
            List of expanded query strings. The original ``query`` is NOT
            included — callers that want it prepended must do so
            themselves. Implementations MUST NOT raise on LLM failure —
            return ``[]`` so the searcher falls back to the original query.
        """
        ...
