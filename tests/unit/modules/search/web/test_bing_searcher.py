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
) -> SimpleNamespace:
    """Build a duck-typed BingSettings stand-in (T013 replaces with real class)."""
    return SimpleNamespace(
        enabled=enabled,
        max_results=max_results,
        timeout=timeout,
        user_agent=user_agent,
        cache_ttl_seconds=cache_ttl_seconds,
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
        # Cache must now contain an entry keyed by (query, effective_max).
        assert ("trending topic", 5) in cache
        assert len(cache[("trending topic", 5)]) == 3

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
        assert len(cache[("trending topic", 5)]) == 3  # cache entry untouched

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
        assert ("topic", 2) in cache
        assert ("topic", 5) not in cache
        await searcher.search("topic", max_results=5)
        assert ("topic", 5) in cache
        assert fetcher.fetch.await_count == 2  # distinct keys → distinct fetches
