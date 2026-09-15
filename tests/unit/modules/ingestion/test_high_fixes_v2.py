# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Regression tests: ingestion module fixes.

Covers:
- RetryQueue zrem divergence logging
- Crawl4AIFetcher lazy-init race + failed-start cleanup
- BoundedLockDict eviction skips locked entries
- HttpxFetcher raise_for_status activates HTTPStatusError branch
- Plugin module-name collision / idempotent reload
- RSSParser._parse_date UTC interpretation
- SourceScheduler.schedule_source public runtime API
- SourceConfigRepo.get_credibility exact-host lookup
"""

from __future__ import annotations

import asyncio
import sys
import time
from calendar import timegm
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from unittest.mock import PropertyMock

from modules.ingestion.deduplication.retry import RetryQueue
from modules.ingestion.fetching.rate_limiter import BoundedLockDict
from modules.ingestion.parsing.rss_parser import RSSParser
from modules.ingestion.scheduling.scheduler import SourceScheduler

# ---------------------------------------------------------------------------
# — zrem divergence surfaced
# ---------------------------------------------------------------------------


class TestRetryQueueZremDivergence:
    @pytest.mark.asyncio
    async def test_zrem_fewer_than_fetched_logs_warning(self, caplog):
        cache = MagicMock()
        cache.zrangebyscore = AsyncMock(return_value=['{"url":"u","host":"h"}'])
        cache.zrem = AsyncMock(return_value=0)  # already claimed concurrently

        queue = RetryQueue(cache)
        result = await queue.get_due_items("example.com")

        assert len(result) == 1
        cache.zrem.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_items_skips_zrem(self):
        cache = MagicMock()
        cache.zrangebyscore = AsyncMock(return_value=[])
        cache.zrem = AsyncMock()

        queue = RetryQueue(cache)
        assert await queue.get_due_items("example.com") == []
        cache.zrem.assert_not_awaited()


# ---------------------------------------------------------------------------
# — crawl4ai lazy init
# ---------------------------------------------------------------------------


def _fake_crawl4ai_module(start_behavior: str = "ok") -> SimpleNamespace:
    crawler = MagicMock()
    if start_behavior == "fail":
        crawler.start = AsyncMock(side_effect=RuntimeError("boom"))
        crawler.close = AsyncMock()
    else:
        crawler.start = AsyncMock()
    module = SimpleNamespace(
        AsyncWebCrawler=MagicMock(return_value=crawler),
        BrowserConfig=MagicMock(),
    )
    return module, crawler


class TestCrawl4AILazyInit:
    @pytest.mark.asyncio
    async def test_concurrent_fetch_initializes_once(self):
        """Two concurrent fetch calls share a single crawler instance."""
        from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher

        module, crawler = _fake_crawl4ai_module()
        crawler.arun = AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                status_code=200,
                html="<html></html>",
                response_headers={},
            )
        )
        fetcher = Crawl4AIFetcher()

        with patch.dict(sys.modules, {"crawl4ai": module}):
            await asyncio.gather(
                fetcher.fetch("https://example.com"),
                fetcher.fetch("https://example.org"),
            )

        assert module.AsyncWebCrawler.call_count == 1
        assert fetcher._initialized is True

    @pytest.mark.asyncio
    async def test_failed_start_does_not_leak_instance(self):
        """start failure leaves fetcher uninitialized and closes crawler."""
        from modules.ingestion.fetching.crawl4ai_fetcher import Crawl4AIFetcher

        module, crawler = _fake_crawl4ai_module(start_behavior="fail")
        fetcher = Crawl4AIFetcher()

        with (
            patch.dict(sys.modules, {"crawl4ai": module}),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await fetcher.fetch("https://example.com")

        assert fetcher._initialized is False
        assert fetcher._crawler is None
        crawler.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# — lock eviction skips busy locks
# ---------------------------------------------------------------------------


class TestBoundedLockDictEviction:
    @pytest.mark.asyncio
    async def test_eviction_skips_locked_entries(self):
        d = BoundedLockDict(maxsize=2)

        busy = d["a"]
        async with busy:  # hold the lock so locked is True
            d["b"]
            # capacity reached; oldest ("a") is locked — must not be evicted
            d["c"]

        assert "a" in d, "busy lock was evicted"
        assert d["a"] is busy

    def test_evicts_idle_oldest_when_not_locked(self):
        d = BoundedLockDict(maxsize=2)
        d["a"]
        d["b"]
        d["c"]  # "a" idle → evicted
        assert "a" not in d
        assert "b" in d and "c" in d


# ---------------------------------------------------------------------------
# — raise_for_status makes HTTPStatusError branch reachable
# ---------------------------------------------------------------------------


class TestHttpxErrorStatusRaises:
    @pytest.mark.asyncio
    async def test_500_response_raises_http_status_error(self):
        """A real 500 response now raises HTTPStatusError (previously the
        branch was dead code and (500, text, headers) was returned)."""
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        request = httpx.Request("GET", "https://example.com")
        response_500 = httpx.Response(500, request=request)

        fetcher = HttpxFetcher()
        with (
            patch.object(fetcher._client, "build_request", return_value=request) as _build,
            patch.object(
                fetcher._client,
                "send",
                new_callable=AsyncMock,
                return_value=response_500,
            ),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await fetcher.fetch("https://example.com")

    @pytest.mark.asyncio
    async def test_200_response_returned_normally(self):
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher

        request = httpx.Request("GET", "https://example.com")
        response = httpx.Response(200, text="ok", request=request)

        fetcher = HttpxFetcher()
        with (
            patch.object(fetcher._client, "build_request", return_value=request),
            patch.object(fetcher._client, "send", new_callable=AsyncMock, return_value=response),
        ):
            status, text, _headers = await fetcher.fetch("https://example.com")

        assert status == 200
        assert text == "ok"


# ---------------------------------------------------------------------------
# — plugin module name collision
# ---------------------------------------------------------------------------


class TestPluginModuleNameUniqueness:
    @staticmethod
    def _plugin_body(unique_name: str) -> str:
        # Plugins must register via the decorator: a module that only
        # defines create_parser() never contributes a parser instance.
        return (
            "from modules.ingestion.parsing.plugin import source_parser_plugin\n"
            f"@source_parser_plugin(name={unique_name!r})\n"
            "class P:\n"
            "    pass\n"
        )

    def test_same_stem_in_two_dirs_no_collision(self, tmp_path):
        from modules.ingestion.parsing import plugin as plugin_mod
        from modules.ingestion.parsing.plugin import discover_plugins_from_directory

        saved = dict(plugin_mod._plugin_registry)
        plugin_mod._plugin_registry.clear()
        try:
            dir_a = tmp_path / "a"
            dir_b = tmp_path / "b"
            dir_a.mkdir()
            dir_b.mkdir()
            (dir_a / "feed.py").write_text(self._plugin_body("feed_a"), encoding="utf-8")
            (dir_b / "feed.py").write_text(self._plugin_body("feed_b"), encoding="utf-8")

            loaded_a = discover_plugins_from_directory(dir_a)
            loaded_b = discover_plugins_from_directory(dir_b)

            assert len(loaded_a) == 1
            assert len(loaded_b) == 1
            assert loaded_a[0] != loaded_b[0], (
                "distinct files must map to distinct sys.modules keys"
            )
        finally:
            plugin_mod._plugin_registry.clear()
            plugin_mod._plugin_registry.update(saved)

    def test_rescan_is_idempotent(self, tmp_path):
        from modules.ingestion.parsing import plugin as plugin_mod
        from modules.ingestion.parsing.plugin import discover_plugins_from_directory

        saved = dict(plugin_mod._plugin_registry)
        plugin_mod._plugin_registry.clear()
        try:
            directory = tmp_path / "plugins"
            directory.mkdir()
            (directory / "feed.py").write_text(self._plugin_body("feed_rescan"), encoding="utf-8")

            first = discover_plugins_from_directory(directory)
            first_load_calls = [k for k in sys.modules if k.startswith("weaver_source_plugins.")]
            discover_plugins_from_directory(directory)
            second_load_calls = [k for k in sys.modules if k.startswith("weaver_source_plugins.")]

            assert len(first) == 1
            # Re-scan must not re-execute the module (no duplicate keys).
            assert len(first_load_calls) == len(second_load_calls)
        finally:
            plugin_mod._plugin_registry.clear()
            plugin_mod._plugin_registry.update(saved)


# ---------------------------------------------------------------------------
# — UTC interpretation of feedparser struct_time
# ---------------------------------------------------------------------------


class TestRssParseDateUtc:
    def test_published_parsed_interpreted_as_utc(self):
        # 2024-01-02 03:04:05 UTC
        published = time.struct_time((2024, 1, 2, 3, 4, 5, 1, 2, 0))
        entry = {"published_parsed": published}

        result = RSSParser._parse_date(entry)

        assert result is not None
        assert result.timestamp() == timegm(published)

    def test_missing_date_returns_none(self):
        assert RSSParser._parse_date({}) is None


# ---------------------------------------------------------------------------
# — runtime schedule_source
# ---------------------------------------------------------------------------


def _make_source(source_id: str = "src-1", enabled: bool = True):
    from modules.ingestion.domain.models import SourceConfig

    return SourceConfig(
        id=source_id,
        name="s",
        url="https://example.com/feed",
        source_type="rss",
        enabled=enabled,
        interval_minutes=30,
    )


class TestSourceSchedulerRuntimeScheduling:
    def _scheduler(self):
        registry = MagicMock()
        callback = AsyncMock()
        return SourceScheduler(registry, callback)

    def test_schedule_source_noop_when_not_running(self):
        scheduler = self._scheduler()
        scheduler._scheduler.add_job = MagicMock()
        scheduler.schedule_source(_make_source())
        scheduler._scheduler.add_job.assert_not_called()

    def test_schedule_source_registers_job_when_running(self):
        scheduler = self._scheduler()
        scheduler._scheduler.add_job = MagicMock()
        with patch.object(
            type(scheduler._scheduler), "running", new_callable=PropertyMock, return_value=True
        ):
            scheduler.schedule_source(_make_source())

        scheduler._scheduler.add_job.assert_called_once()
        kwargs = scheduler._scheduler.add_job.call_args.kwargs
        assert kwargs["id"] == "source_src-1"

    def test_unschedule_source_removes_job(self):
        scheduler = self._scheduler()
        scheduler._scheduler.remove_job = MagicMock()

        scheduler.unschedule_source("src-1")

        scheduler._scheduler.remove_job.assert_called_once_with("source_src-1")


# ---------------------------------------------------------------------------
# — get_credibility exact-host lookup
# ---------------------------------------------------------------------------


class TestGetCredibility:
    def _repo_with_session(self, rows):
        from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        authority_result = MagicMock()
        authority_result.scalar_one_or_none.return_value = None

        source_rows = MagicMock()
        source_rows.scalars.return_value = rows

        session.execute = AsyncMock(side_effect=[authority_result, source_rows])
        pool = MagicMock()
        pool.session = MagicMock(return_value=session)
        return SourceConfigRepo(pool)

    @pytest.mark.asyncio
    async def test_authority_table_hit(self):
        from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo

        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        authority_result = MagicMock()
        authority_result.scalar_one_or_none.return_value = 0.8
        session.execute = AsyncMock(return_value=authority_result)
        pool = MagicMock()
        pool.session = MagicMock(return_value=session)

        repo = SourceConfigRepo(pool)
        assert await repo.get_credibility("example.com") == 0.8

    @pytest.mark.asyncio
    async def test_multiple_matching_rows_no_crash(self):
        """Multiple SourceConfig rows with credibility must not raise
        MultipleResultsFound; first authority match wins."""
        row_match = SimpleNamespace(url="https://github.com/feed", credibility=0.7)
        row_other = SimpleNamespace(url="https://a.com/github.com/other", credibility=0.4)
        repo = self._repo_with_session([row_other, row_match])
        assert await repo.get_credibility("github.com") == 0.7

    @pytest.mark.asyncio
    async def test_host_in_path_does_not_match(self):
        row = SimpleNamespace(url="https://a.com/github.com/feed", credibility=0.4)
        repo = self._repo_with_session([row])
        assert await repo.get_credibility("github.com") is None
