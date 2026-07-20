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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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

    async def search(self, query: str, max_results: int | None = None) -> list[BingSearchResult]:
        """Search the web for ``query`` and return up to ``max_results`` hits.

        Args:
            query: Search query string (non-empty, caller-validated).
            max_results: Upper bound on returned results. Implementations
                may return fewer (including an empty list) when the backend
                yields fewer hits or fails gracefully. ``None`` (default)
                lets the implementation fall back to its configured
                ``settings.max_results`` so the effective cap is defined in
                one place (DRY) — see ``BingSearcher.search``.

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
