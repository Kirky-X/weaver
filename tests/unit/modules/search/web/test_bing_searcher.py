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

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from cachetools import TTLCache

from modules.ingestion.fetching.base import BaseFetcher
from modules.search.web import BingSearchResult
from modules.search.web.bing_searcher import BingSearcher

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _make_settings(
    *,
    enabled: bool = True,
    max_results: int = 5,
    timeout: int = 15,
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    cache_ttl_seconds: int = 0,
    # R-web-search-008 fields. Defaulted to OFF in the test stand-in so
    # legacy tests (which assume general-only /search) continue to pass
    # without modification. New tests opt-in by setting these to True /
    # non-"none". The real BingSettings class defaults news_enabled=True
    # and time_filter="week" — that production default is exercised by the
    # new TestBingSearcherMode / TestBingSearcherTimeFilter test classes.
    news_enabled: bool = False,
    news_max_results: int = 8,
    time_filter: str = "none",
    query_expansion_enabled: bool = False,
    query_expansion_max_terms: int = 3,
    query_expansion_timeout: float = 5.0,
) -> SimpleNamespace:
    """Build a duck-typed BingSettings stand-in (T013 replaces with real class)."""
    return SimpleNamespace(
        enabled=enabled,
        max_results=max_results,
        timeout=timeout,
        user_agent=user_agent,
        cache_ttl_seconds=cache_ttl_seconds,
        news_enabled=news_enabled,
        news_max_results=news_max_results,
        time_filter=time_filter,
        query_expansion_enabled=query_expansion_enabled,
        query_expansion_max_terms=query_expansion_max_terms,
        query_expansion_timeout=query_expansion_timeout,
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


class TestBingSearcherParserIntegration:
    """Integration tests for search() + parse_bing_html() wiring (T006).

    These tests use the shared ``bing_sample.html`` fixture to verify that
    ``search()`` returns real parsed results (not the empty list from T003
    skeleton) and that ``max_results`` propagates end-to-end to the parser.
    """

    @pytest.mark.asyncio
    async def test_search_returns_parsed_results_from_fixture(self) -> None:
        """search() must return parsed BingSearchResult entries from fixture HTML.

        T006 contract: search() wires parse_bing_html() — given the fixture
        (3 valid results + 2 skipped + 2 non-result list items), it must
        return exactly 3 BingSearchResult instances with title/url/snippet
        populated.
        """
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("test query")
        assert len(results) == 3
        for r in results:
            assert isinstance(r, BingSearchResult)
            assert r.title
            assert r.url.startswith("https://example.com/")
            assert r.snippet  # fixture provides snippet for all valid entries

    @pytest.mark.asyncio
    async def test_search_max_results_propagates_to_parser(self) -> None:
        """max_results argument must cap the returned result count.

        Fixture has 3 valid results; asking for 2 must yield exactly 2.
        This is the end-to-end version of TestParseBingHtmlMaxResults.
        """
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("test query", max_results=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_results_preserve_fixture_order(self) -> None:
        """Result order must match fixture DOM order (no reshuffling)."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        results = await searcher.search("test query")
        titles = [r.title for r in results]
        assert titles == [
            "First Test Article Title",
            "Second Test Article Title",
            "Third Article With Whitespace",
        ]

    @pytest.mark.asyncio
    async def test_search_max_results_none_falls_back_to_settings(self) -> None:
        """max_results=None must fall back to settings.max_results (DRY).

        Architecture review M2: when caller omits max_results, the effective
        cap comes from settings — avoiding dual default-value drift.
        """
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        # Settings says max_results=2; caller passes None.
        fetcher = _make_fetcher(html=html)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(max_results=2),
        )
        results = await searcher.search("test query", max_results=None)
        # Fixture has 3 valid results; settings cap of 2 must apply.
        assert len(results) == 2
        assert results[0].title == "First Test Article Title"
        assert results[1].title == "Second Test Article Title"

    @pytest.mark.asyncio
    async def test_search_explicit_max_results_overrides_settings(self) -> None:
        """Explicit max_results must override settings.max_results."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        # Settings says max_results=2; caller overrides to 1.
        fetcher = _make_fetcher(html=html)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(max_results=2),
        )
        results = await searcher.search("test query", max_results=1)
        assert len(results) == 1
        assert results[0].title == "First Test Article Title"


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


class TestBingSearcherCache:
    """Tests for BingSearcher TTL cache (LOW-2 perf fix).

    Covers: cache miss (fetcher called, result cached), cache hit (fetcher
    NOT called), TTL expiry (entry disappears after TTL), cache write
    failure (non-fatal — search still returns result), and cache disabled
    (ttl=0 means no caching).
    """

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result_and_calls_fetcher(self) -> None:
        """On cache miss, fetcher is called and result is stored in cache."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        cache = TTLCache(maxsize=10, ttl=1800)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(),
            cache=cache,
        )
        # First call: cache miss → fetcher called, result cached.
        results = await searcher.search("trending topic")
        assert len(results) == 3
        fetcher.fetch.assert_awaited_once()
        # Cache key includes (query, effective_max, resolved_mode,
        # effective_time_filter). With news_enabled=False, mode="auto"
        # resolves to "general"; time_filter defaults to "none".
        assert ("trending topic", 5, "general", "none") in cache
        assert len(cache[("trending topic", 5, "general", "none")]) == 3

    @pytest.mark.asyncio
    async def test_cache_hit_skips_fetcher_and_returns_cached(self) -> None:
        """On cache hit, fetcher is NOT called and cached result is returned."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        cache = TTLCache(maxsize=10, ttl=1800)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(),
            cache=cache,
        )
        # Prime the cache.
        first_results = await searcher.search("trending topic")
        assert fetcher.fetch.await_count == 1
        # Second call with same query + max_results: cache hit.
        second_results = await searcher.search("trending topic")
        assert fetcher.fetch.await_count == 1  # no additional fetcher call
        assert second_results == first_results
        # Returned list must be a COPY (caller mutation must not corrupt cache).
        second_results.clear()
        assert len(cache[("trending topic", 5, "general", "none")]) == 3  # cache entry untouched

    @pytest.mark.asyncio
    async def test_cache_hit_with_explicit_max_results_matches_settings_default(self) -> None:
        """Passing max_results=5 explicitly must hit cache populated by None-default call.

        effective_max normalizes both to settings.max_results=5, so they
        share the same cache key.
        """
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        cache = TTLCache(maxsize=10, ttl=1800)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(max_results=5),
            cache=cache,
        )
        # Prime with explicit max_results=5 (matches settings default).
        await searcher.search("topic", max_results=5)
        assert fetcher.fetch.await_count == 1
        # Call with default max_results (None → settings.max_results=5).
        await searcher.search("topic")
        assert fetcher.fetch.await_count == 1  # cache hit

    @pytest.mark.asyncio
    async def test_cache_ttl_expiry_triggers_refetch(self) -> None:
        """After TTL expires, fetcher is called again (cache miss)."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        # Use a 1-second TTL so the test doesn't slow down the suite much.
        cache = TTLCache(maxsize=10, ttl=1)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(),
            cache=cache,
        )
        await searcher.search("trending topic")
        assert fetcher.fetch.await_count == 1
        # Wait for TTL to expire.
        await asyncio.sleep(1.1)
        # Cache entry must be gone (TTLCache evicts lazily on access).
        results = await searcher.search("trending topic")
        assert fetcher.fetch.await_count == 2  # refetched after expiry
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_cache_write_failure_does_not_block_search(self) -> None:
        """If cache.__setitem__ raises, search() must still return results.

        Rule 12: failures explicit. Cache write failure is non-fatal —
        logged and the search flow continues with the freshly-fetched
        result.
        """
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)

        # Build a cache whose __setitem__ always raises.
        class _BrokenCache(TTLCache):
            def __setitem__(self, key, value):
                raise RuntimeError("cache backend down")

        cache = _BrokenCache(maxsize=10, ttl=1800)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(),
            cache=cache,
        )
        # search() must NOT propagate the cache write error.
        results = await searcher.search("trending topic")
        assert len(results) == 3  # result still returned
        fetcher.fetch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_disabled_when_ttl_zero(self) -> None:
        """cache_ttl_seconds=0 must disable caching (fetcher always called)."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        # settings.cache_ttl_seconds=0 → no cache constructed.
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(cache_ttl_seconds=0),
        )
        assert searcher._cache is None
        # Two calls → two fetcher invocations (no caching).
        await searcher.search("topic")
        await searcher.search("topic")
        assert fetcher.fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_cache_enabled_when_ttl_positive(self) -> None:
        """cache_ttl_seconds>0 must construct an internal TTLCache."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(cache_ttl_seconds=1800),
        )
        assert searcher._cache is not None
        assert searcher._cache.ttl == 1800

    @pytest.mark.asyncio
    async def test_cache_uses_query_and_max_results_in_key(self) -> None:
        """Different max_results values must produce distinct cache entries.

        Same query with different max_results cap should not share results
        (parsed list is already client-truncated to the requested cap).
        """
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        cache = TTLCache(maxsize=10, ttl=1800)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(),
            cache=cache,
        )
        await searcher.search("topic", max_results=2)
        assert ("topic", 2, "general", "none") in cache
        assert ("topic", 5, "general", "none") not in cache
        await searcher.search("topic", max_results=5)
        assert ("topic", 5, "general", "none") in cache
        assert fetcher.fetch.await_count == 2  # distinct keys → distinct fetches


def _make_news_fetcher(html_map: dict[str, str] | None = None) -> AsyncMock:
    """Create a fetcher that returns different HTML based on URL path.

    Args:
        html_map: Maps URL path (e.g. "/search", "/news/search") to HTML
            content. When a path is not in the map, returns empty HTML.
            When None, returns the same general-sample HTML for all paths
            (simplified case for tests that don't distinguish).
    """
    fetcher = AsyncMock(spec=BaseFetcher)

    general_html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
    news_html = (_FIXTURE_DIR / "bing_news_sample.html").read_text(encoding="utf-8")

    if html_map is None:
        html_map = {"/search": general_html, "/news/search": news_html}

    async def _fetch(url: str, headers: dict | None = None) -> tuple[int, str, dict]:
        parsed = urlparse(url)
        html = html_map.get(parsed.path, "<html></html>")
        return (200, html, {"Content-Type": "text/html"})

    fetcher.fetch = AsyncMock(side_effect=_fetch)
    fetcher.close = AsyncMock(return_value=None)
    return fetcher


def _make_expander(terms: list[str] | None = None, raises: bool = False) -> AsyncMock:
    """Create an AsyncMock standing in for QueryExpanderProtocol.

    Args:
        terms: Expanded query terms to return. When None, returns []
            (no expansion). When raises=True, the mock raises an
            exception instead of returning terms.
    """
    from modules.search.web.protocol import QueryExpanderProtocol

    expander = AsyncMock(spec=QueryExpanderProtocol)
    if raises:
        expander.expand = AsyncMock(side_effect=RuntimeError("LLM down"))
    else:
        expander.expand = AsyncMock(return_value=list(terms or []))
    return expander


class TestBingSearcherMode:
    """Tests for BingSearcher.search() mode parameter (R-web-search-008).

    Covers all four mode values (auto/general/news/all) and their
    interaction with settings.news_enabled.
    """

    @pytest.mark.asyncio
    async def test_mode_general_calls_only_general_path(self) -> None:
        """mode='general' must hit only /search (never /news/search)."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=True),  # mode overrides this
        )
        await searcher.search("q", mode="general")
        # Exactly one fetcher call, and its URL path is /search.
        assert fetcher.fetch.await_count == 1
        url = fetcher.fetch.call_args.args[0]
        assert urlparse(url).path == "/search"

    @pytest.mark.asyncio
    async def test_mode_news_calls_only_news_path(self) -> None:
        """mode='news' must hit only /news/search (never /search)."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=False),  # mode overrides this
        )
        await searcher.search("q", mode="news")
        assert fetcher.fetch.await_count == 1
        url = fetcher.fetch.call_args.args[0]
        assert urlparse(url).path == "/news/search"

    @pytest.mark.asyncio
    async def test_mode_all_calls_both_paths(self) -> None:
        """mode='all' must hit both /search and /news/search."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=False),  # mode overrides this
        )
        await searcher.search("q", mode="all")
        assert fetcher.fetch.await_count == 2
        paths = sorted(urlparse(c.args[0]).path for c in fetcher.fetch.call_args_list)
        assert paths == ["/news/search", "/search"]

    @pytest.mark.asyncio
    async def test_mode_auto_with_news_enabled_calls_both(self) -> None:
        """mode='auto' + news_enabled=True must hit both paths."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=True),
        )
        await searcher.search("q", mode="auto")
        assert fetcher.fetch.await_count == 2
        paths = sorted(urlparse(c.args[0]).path for c in fetcher.fetch.call_args_list)
        assert paths == ["/news/search", "/search"]

    @pytest.mark.asyncio
    async def test_mode_auto_with_news_disabled_calls_only_general(self) -> None:
        """mode='auto' + news_enabled=False must hit only /search (legacy)."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=False),
        )
        await searcher.search("q", mode="auto")
        assert fetcher.fetch.await_count == 1
        url = fetcher.fetch.call_args.args[0]
        assert urlparse(url).path == "/search"

    @pytest.mark.asyncio
    async def test_mode_all_merges_general_and_news_results(self) -> None:
        """mode='all' must merge results from both verticals."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=False, max_results=10, news_max_results=10),
        )
        results = await searcher.search("q", mode="all", max_results=10)
        # General fixture has 3 results, news fixture has 4 (3 newsitem + 1 b_algo).
        # After dedup by URL (URLs differ across fixtures), merged count is 7.
        assert len(results) >= 3  # at least general results present
        # Verify URLs from both fixtures appear (cross-check dedup didn't drop all).
        # Compare parsed hostname (== "example.com" or *.example.com) instead of a
        # substring check — semantically stricter and avoids a CodeQL false positive
        # (py/incomplete-url-substring-sanitization) misreading the assertion as URL
        # sanitization.
        urls = {r.url for r in results}
        assert any(
            (h := urlparse(u).hostname) is not None
            and (h == "example.com" or h.endswith(".example.com"))
            for u in urls
        )

    @pytest.mark.asyncio
    async def test_mode_all_deduplicates_by_url(self) -> None:
        """mode='all' must deduplicate results by URL across verticals."""
        # Build a fetcher that returns the SAME HTML (with same URLs) for
        # both /search and /news/search — the dedup logic must collapse them.
        same_html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_news_fetcher(html_map={"/search": same_html, "/news/search": same_html})
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(max_results=10, news_max_results=10),
        )
        results = await searcher.search("q", mode="all", max_results=10)
        # Both verticals returned the same 3 URLs → dedup yields 3 (not 6).
        urls = [r.url for r in results]
        assert len(urls) == len(set(urls))  # no duplicates
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_mode_general_ignores_news_max_results(self) -> None:
        """mode='general' must not invoke news search at all (news_max_results unused)."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=True, news_max_results=99),
        )
        await searcher.search("q", mode="general")
        assert fetcher.fetch.await_count == 1
        url = fetcher.fetch.call_args.args[0]
        assert urlparse(url).path == "/search"


class TestBingSearcherTimeFilter:
    """Tests for BingSearcher.search() time_filter parameter."""

    @pytest.mark.asyncio
    async def test_time_filter_day_adds_filters_param(self) -> None:
        """time_filter='day' must add filters=ex1:"ez5_86400_1" to URL."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.search("q", mode="general", time_filter="day")
        url = fetcher.fetch.call_args.args[0]
        # URL must contain the filters parameter (URL-encoded form).
        # quote('ex1:"ez5_86400_1"', safe='') → 'ex1%3A%22ez5_86400_1%22'
        assert "86400" in url
        assert "ez5_" in url

    @pytest.mark.asyncio
    async def test_time_filter_week_adds_filters_param(self) -> None:
        """time_filter='week' must add filters=ex1:"ez5_604800_7" to URL."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.search("q", mode="general", time_filter="week")
        url = fetcher.fetch.call_args.args[0]
        assert "604800" in url
        assert "ez5_" in url

    @pytest.mark.asyncio
    async def test_time_filter_month_adds_filters_param(self) -> None:
        """time_filter='month' must add filters=ex1:"ez5_2592000_30" to URL."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.search("q", mode="general", time_filter="month")
        url = fetcher.fetch.call_args.args[0]
        assert "2592000" in url
        assert "ez5_" in url

    @pytest.mark.asyncio
    async def test_time_filter_none_no_filters_param(self) -> None:
        """time_filter='none' must NOT add filters param to URL (legacy)."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(fetcher=fetcher, settings=_make_settings())
        await searcher.search("q", mode="general", time_filter="none")
        url = fetcher.fetch.call_args.args[0]
        assert "filters" not in url
        assert "ez5_" not in url

    @pytest.mark.asyncio
    async def test_time_filter_none_falls_back_to_settings(self) -> None:
        """time_filter=None must defer to settings.time_filter."""
        fetcher = _make_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(time_filter="week"),
        )
        await searcher.search("q", mode="general", time_filter=None)
        url = fetcher.fetch.call_args.args[0]
        assert "604800" in url  # settings.week applied

    @pytest.mark.asyncio
    async def test_time_filter_only_applied_to_general_search(self) -> None:
        """time_filter must NOT be applied to news search URL (news is already time-sorted)."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(),
        )
        await searcher.search("q", mode="all", time_filter="week")
        # Two calls: /search and /news/search. Only /search should have filters.
        for call in fetcher.fetch.call_args_list:
            url = call.args[0]
            parsed = urlparse(url)
            if parsed.path == "/news/search":
                assert "filters" not in url, "News URL must not have time_filter"
            else:
                assert "604800" in url, "General URL must have time_filter"


class TestBingSearcherQueryExpansion:
    """Tests for BingSearcher.search() query expansion (R-web-search-008)."""

    @pytest.mark.asyncio
    async def test_expansion_enabled_runs_multiple_queries(self) -> None:
        """When query_expansion_enabled and expander returns terms, all are searched."""
        fetcher = _make_news_fetcher()
        expander = _make_expander(terms=["菲律宾 仁爱礁", "菲律宾 南海"])
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(
                news_enabled=False,
                query_expansion_enabled=True,
                query_expansion_max_terms=3,
            ),
            query_expander=expander,
        )
        await searcher.search("菲律宾", mode="general")
        # Original + 2 expanded = 3 queries, each hits general search once.
        assert fetcher.fetch.await_count == 3
        # Verify expander was called with the original query.
        expander.expand.assert_awaited_once()
        call_kwargs = expander.expand.call_args.kwargs
        assert call_kwargs["max_terms"] == 3

    @pytest.mark.asyncio
    async def test_expansion_disabled_does_not_call_expander(self) -> None:
        """When query_expansion_enabled=False, expander is never called."""
        fetcher = _make_news_fetcher()
        expander = _make_expander(terms=["should_not_be_called"])
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(query_expansion_enabled=False),
            query_expander=expander,
        )
        await searcher.search("q", mode="general")
        expander.expand.assert_not_called()
        assert fetcher.fetch.await_count == 1  # only original query

    @pytest.mark.asyncio
    async def test_expansion_no_expander_falls_back_to_original_only(self) -> None:
        """When query_expansion_enabled but no expander injected, only original searched."""
        fetcher = _make_news_fetcher()
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(query_expansion_enabled=True),
            query_expander=None,  # no expander injected
        )
        await searcher.search("q", mode="general")
        assert fetcher.fetch.await_count == 1

    @pytest.mark.asyncio
    async def test_expansion_returns_empty_falls_back_to_original_only(self) -> None:
        """When expander returns [], only original query is searched."""
        fetcher = _make_news_fetcher()
        expander = _make_expander(terms=[])
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(query_expansion_enabled=True),
            query_expander=expander,
        )
        await searcher.search("q", mode="general")
        assert fetcher.fetch.await_count == 1

    @pytest.mark.asyncio
    async def test_expansion_failure_falls_back_to_original_only(self) -> None:
        """When expander raises, only original query is searched (graceful degradation)."""
        fetcher = _make_news_fetcher()
        expander = _make_expander(raises=True)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(query_expansion_enabled=True),
            query_expander=expander,
        )
        results = await searcher.search("q", mode="general")
        # Expansion failed → only original query searched → at least 1 result returned.
        assert fetcher.fetch.await_count == 1
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_expansion_results_deduplicated_by_url(self) -> None:
        """Expansion queries' results must be deduplicated by URL."""
        # All three queries return the SAME fixture → only 3 unique URLs total.
        fetcher = _make_news_fetcher()
        expander = _make_expander(terms=["expanded1", "expanded2"])
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(
                news_enabled=False,
                query_expansion_enabled=True,
                max_results=10,
            ),
            query_expander=expander,
        )
        results = await searcher.search("original", mode="general", max_results=10)
        urls = [r.url for r in results]
        assert len(urls) == len(set(urls))  # no duplicates

    @pytest.mark.asyncio
    async def test_expansion_truncates_to_max_results_after_merge(self) -> None:
        """Final result count must respect max_results after merge+dedup."""
        # Each query returns 3 results; with 1 original + 2 expanded = 3 queries,
        # total before dedup = 9. After dedup (same fixture) = 3. After truncation
        # to max_results=2 = 2.
        fetcher = _make_news_fetcher()
        expander = _make_expander(terms=["expanded1", "expanded2"])
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(
                news_enabled=False,
                query_expansion_enabled=True,
                max_results=10,
            ),
            query_expander=expander,
        )
        results = await searcher.search("original", mode="general", max_results=2)
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_expansion_timeout_falls_back_to_original_only(self) -> None:
        """When expander times out, only original query is searched."""
        import asyncio

        fetcher = _make_news_fetcher()

        class _SlowExpander:
            async def expand(self, query: str, *, max_terms: int = 3) -> list[str]:
                # Sleep longer than the configured timeout.
                await asyncio.sleep(10)
                return ["should_never_return"]

        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(
                query_expansion_enabled=True,
                query_expansion_timeout=0.1,  # 100ms timeout
            ),
            query_expander=_SlowExpander(),
        )
        results = await searcher.search("q", mode="general")
        # Timeout → only original query searched.
        assert fetcher.fetch.await_count == 1
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_expansion_with_mode_all_runs_both_verticals_per_query(self) -> None:
        """mode='all' + expansion must run both general+news for each expanded query."""
        fetcher = _make_news_fetcher()
        expander = _make_expander(terms=["expanded1"])
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(
                news_enabled=False,
                query_expansion_enabled=True,
            ),
            query_expander=expander,
        )
        # 1 original + 1 expanded = 2 queries; mode='all' = 2 verticals each = 4 fetches.
        await searcher.search("original", mode="all")
        assert fetcher.fetch.await_count == 4


class TestBingSearcherCacheKeyEvolution:
    """Verify cache key now includes mode and time_filter (R-web-search-008).

    Without these components, a cache hit for mode='general' would
    incorrectly return mode='news' results. The 4-tuple key
    (query, effective_max, resolved_mode, effective_time_filter) prevents
    cross-mode / cross-time-filter contamination.
    """

    @pytest.mark.asyncio
    async def test_cache_key_differs_by_mode(self) -> None:
        """Different modes must produce distinct cache entries."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        cache = TTLCache(maxsize=10, ttl=1800)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(news_enabled=False),
            cache=cache,
        )
        await searcher.search("topic", mode="general")
        await searcher.search("topic", mode="news")
        # Two distinct cache entries (mode differs).
        assert ("topic", 5, "general", "none") in cache
        assert ("topic", 5, "news", "none") in cache
        assert fetcher.fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_cache_key_differs_by_time_filter(self) -> None:
        """Different time_filter values must produce distinct cache entries."""
        html = (_FIXTURE_DIR / "bing_sample.html").read_text(encoding="utf-8")
        fetcher = _make_fetcher(html=html)
        cache = TTLCache(maxsize=10, ttl=1800)
        searcher = BingSearcher(
            fetcher=fetcher,
            settings=_make_settings(),
            cache=cache,
        )
        await searcher.search("topic", mode="general", time_filter="none")
        await searcher.search("topic", mode="general", time_filter="week")
        assert ("topic", 5, "general", "none") in cache
        assert ("topic", 5, "general", "week") in cache
        assert fetcher.fetch.await_count == 2
