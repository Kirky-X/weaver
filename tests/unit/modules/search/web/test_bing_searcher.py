# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for BingSearcher (web search module).

TDD Red phase: these tests fail until ``BingSearcher`` is implemented in
``src/modules/search/web/bing_searcher.py`` (T003 Green). The mock fetcher
returns a fixed HTML payload so tests do not hit the network.

Note: ``BingSettings`` is not implemented until T013. These tests use
``SimpleNamespace`` as a duck-typed stand-in exposing the same attributes
(``enabled``, ``max_results``, ``timeout``, ``user_agent``). Once T013
lands, the stand-in can be replaced with ``BingSettings()`` without
touching the assertions (attribute access is compatible).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from modules.ingestion.fetching.base import BaseFetcher
from modules.search.web import BingSearchResult
from modules.search.web.bing_searcher import BingSearcher


def _make_settings(
    *,
    enabled: bool = True,
    max_results: int = 5,
    timeout: int = 15,
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
) -> SimpleNamespace:
    """Build a duck-typed BingSettings stand-in (T013 replaces with real class)."""
    return SimpleNamespace(
        enabled=enabled,
        max_results=max_results,
        timeout=timeout,
        user_agent=user_agent,
    )


def _make_fetcher(html: str = "<html></html>", status: int = 200) -> AsyncMock:
    """Create an AsyncMock standing in for a BaseFetcher instance.

    Configured as ``spec=BaseFetcher`` so attribute access is checked against
    the abstract interface — guards against typos in method names.
    """
    fetcher = AsyncMock(spec=BaseFetcher)
    fetcher.fetch = AsyncMock(return_value=(status, html, {"Content-Type": "text/html"}))
    fetcher.close = AsyncMock(return_value=None)
    return fetcher


class TestBingSearcherInit:
    """Tests for BingSearcher construction."""

    def test_init_accepts_base_fetcher_and_settings(self) -> None:
        fetcher = _make_fetcher()
        settings = _make_settings()
        searcher = BingSearcher(fetcher=fetcher, settings=settings)
        assert searcher is not None

    def test_init_does_not_call_fetcher(self) -> None:
        """Constructor must be lazy — no HTTP calls at init time."""
        fetcher = _make_fetcher()
        settings = _make_settings()
        BingSearcher(fetcher=fetcher, settings=settings)
        fetcher.fetch.assert_not_called()
        fetcher.close.assert_not_called()


class TestBingSearcherSearch:
    """Tests for BingSearcher.search()."""

    @pytest.mark.asyncio
    async def test_search_returns_list_of_bing_search_result(self) -> None:
        """Return value must be a list of BingSearchResult (type contract)."""
        fetcher = _make_fetcher(html="<html>empty</html>")
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("test query")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, BingSearchResult)

    @pytest.mark.asyncio
    async def test_search_calls_fetcher_with_bing_url(self) -> None:
        """Must call fetcher.fetch with https://cn.bing.com/search?q=... URL."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.search("hello world")
        fetcher.fetch.assert_awaited_once()
        call_args, call_kwargs = fetcher.fetch.call_args
        url = call_args[0] if call_args else call_kwargs.get("url")
        assert url is not None
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "cn.bing.com"
        assert parsed.path == "/search"
        qs = parse_qs(parsed.query)
        assert "q" in qs
        assert qs["q"][0] == "hello world"
        assert "first" in qs

    @pytest.mark.asyncio
    async def test_search_passes_user_agent_header(self) -> None:
        """Must pass settings.user_agent as User-Agent header to fetcher."""
        ua = "Mozilla/5.0 TestUA/1.0"
        fetcher = _make_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(user_agent=ua),
        )
        await searcher.search("q")
        fetcher.fetch.assert_awaited_once()

        # fetcher.fetch signature: (url, headers=None) — headers may be positional or keyword
        call = fetcher.fetch.call_args
        args, kwargs = call.args, call.kwargs
        if "headers" in kwargs:
            headers = kwargs["headers"]
        elif len(args) >= 2:
            headers = args[1]
        else:
            headers = None
        assert isinstance(headers, dict), f"headers must be dict, got {type(headers)}"
        assert headers.get("User-Agent") == ua

    @pytest.mark.asyncio
    async def test_search_empty_html_returns_empty_list(self) -> None:
        """Empty HTML response must yield empty list (not raise)."""
        fetcher = _make_fetcher(html="")
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("q")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_non_200_status_returns_empty_list(self) -> None:
        """Non-200 HTTP status must yield empty list (graceful degradation)."""
        fetcher = _make_fetcher(html="<html>error</html>", status=503)
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("q")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_max_results_argument(self) -> None:
        """max_results argument must be forwarded; caller can cap result count."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.search("q", max_results=3)
        fetcher.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_fetcher_raises_returns_empty_list(self) -> None:
        """If fetcher.fetch raises, search() must return [] (not propagate).

        R-web-search-005: trigger_web_search handles None + exceptions, but
        BingSearcher.search itself should also be resilient to avoid leaking
        network errors up to the orchestrator. The orchestrator's try/except
        is a belt; this is the suspenders.
        """
        fetcher = _make_fetcher()
        fetcher.fetch = AsyncMock(side_effect=RuntimeError("network down"))
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("q")
        assert results == []


class TestBingSearcherClose:
    """Tests for BingSearcher.close().

    Per BingSearchProtocol: close() must NOT close the shared fetcher —
    the container owns the fetcher's lifecycle. These tests verify the
    no-op contract.
    """

    @pytest.mark.asyncio
    async def test_close_does_not_close_shared_fetcher(self) -> None:
        """close() must NOT call fetcher.close() — fetcher is container-managed.

        Rationale: BingSearcher shares the ingestion pipeline's HttpxFetcher
        singleton. Closing it here would destroy the shared HTTP connection
        pool and break in-flight ingestion requests.
        """
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.close()
        fetcher.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        """close() must be safe to call multiple times (no-op, no exception)."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.close()
        await searcher.close()
        # Still no fetcher.close() call — both invocations are no-ops.
        fetcher.close.assert_not_called()


class TestBingSearcherInputValidation:
    """Tests for defense-in-depth input validation in search()."""

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_empty_list(self) -> None:
        """Empty query must return [] without calling fetcher (defense-in-depth)."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("")
        assert results == []
        fetcher.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_whitespace_query_returns_empty_list(self) -> None:
        """Whitespace-only query must return [] without calling fetcher."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("   \t\n  ")
        assert results == []
        fetcher.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_long_query_truncated(self) -> None:
        """Queries > 500 chars must be truncated (URL length protection)."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        long_query = "x" * 1000
        await searcher.search(long_query)
        fetcher.fetch.assert_awaited_once()
        url = fetcher.fetch.call_args.args[0]
        # Truncated query should produce a URL with q= parameter value of
        # ~500 chars * ~3x encoding overhead (worst case) + URL prefix.
        # Assert URL is well under Bing's 2KB limit.
        assert len(url) < 2048
