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

TDD stage (T003 Green):
    ``search()`` currently calls the fetcher but returns an empty list —
    HTML parsing is added in T005/T006. This skeleton satisfies the type
    and call contracts asserted by T002 without coupling to the parser.

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
    - ``max_results`` is accepted but not yet used (T003 skeleton). T006
      will pass it to ``parse_bing_html`` for result truncation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from core.observability import get_logger
from modules.search.web.protocol import BingSearchResult

if TYPE_CHECKING:
    from modules.ingestion.fetching.base import BaseFetcher


log = get_logger(__name__)

_BING_SEARCH_URL = "https://cn.bing.com/search"
_DEFAULT_QUERY_LOG_PREFIX = 50
_MAX_QUERY_LEN = 500  # Bing accepts ~2KB URL; cap query at 500 chars to leave room for encoding


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
            attributes ``max_results``, ``timeout``, ``user_agent``).
            ``enabled`` is checked by the container, not here.
    """

    def __init__(self, fetcher: BaseFetcher, settings: Any) -> None:
        self._fetcher = fetcher
        self._settings = settings

    async def search(self, query: str, max_results: int = 5) -> list[BingSearchResult]:
        """Search Bing for ``query`` and return up to ``max_results`` hits.

        T003 Green skeleton: calls the fetcher and returns an empty list.
        T006 will wire in ``parse_bing_html`` to produce real results.

        Args:
            query: Search query. Empty / whitespace-only queries return ``[]``
                without an HTTP call (defense-in-depth, even though callers
                should pre-validate). Queries > 500 chars are truncated.
            max_results: Upper bound on returned results. Currently unused
                (T003 skeleton); T006 will pass to ``parse_bing_html``.

        Returns:
            List of ``BingSearchResult`` (empty until T006 lands the parser;
            empty on HTTP error or non-200 status to avoid blocking the
            main search flow — see R-web-search-005).
        """
        # Defense-in-depth: validate query before constructing URL.
        if not query or not query.strip():
            return []
        if len(query) > _MAX_QUERY_LEN:
            query = query[:_MAX_QUERY_LEN]

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

        # T003 Green: return empty list.
        # TODO(T006): integrate parse_bing_html(html, max_results=max_results)
        # and return the parsed list[BingSearchResult].
        return []

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
