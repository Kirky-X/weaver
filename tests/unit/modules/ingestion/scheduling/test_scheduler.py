# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Unit tests for SourceScheduler."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest


class TestSourceSchedulerInit:
    """Tests for SourceScheduler initialization."""

    def test_init_with_params(self):
        """Test SourceScheduler initializes with params."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        mock_callback = AsyncMock()

        scheduler = SourceScheduler(
            registry=mock_registry,
            on_items_discovered=mock_callback,
        )

        assert scheduler._registry is mock_registry
        assert scheduler._on_items is mock_callback


class TestSourceSchedulerStartStop:
    """Tests for SourceScheduler start/stop."""

    @pytest.fixture
    def scheduler(self):
        """Create SourceScheduler instance."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        mock_registry.list_sources.return_value = []

        return SourceScheduler(
            registry=mock_registry,
            on_items_discovered=AsyncMock(),
        )

    def test_start_schedules_sources(self, scheduler):
        """Test start() schedules all enabled sources."""
        mock_source = MagicMock()
        mock_source.id = "source-1"
        mock_source.interval_minutes = 30

        scheduler._registry.list_sources.return_value = [mock_source]

        with patch.object(scheduler._scheduler, "start") as mock_start:
            with patch.object(scheduler._scheduler, "add_job") as mock_add_job:
                scheduler.start()

                mock_start.assert_called_once()
                mock_add_job.assert_called_once()

    def test_stop_shuts_down_scheduler(self, scheduler):
        """Test stop() shuts down scheduler."""
        with patch.object(
            type(scheduler._scheduler), "running", new_callable=PropertyMock, return_value=True
        ):
            with patch.object(scheduler._scheduler, "shutdown") as mock_shutdown:
                scheduler.stop()

                mock_shutdown.assert_called_once_with(wait=False)

    def test_stop_is_noop_when_scheduler_not_running(self, scheduler):
        """#181: stop() before start() must not raise SchedulerNotRunningError."""
        with patch.object(scheduler._scheduler, "shutdown") as mock_shutdown:
            scheduler.stop()

        mock_shutdown.assert_not_called()

    def test_start_is_noop_when_already_running(self, scheduler):
        """#181: a second start() must not raise SchedulerAlreadyRunningError."""
        with patch.object(
            type(scheduler._scheduler), "running", new_callable=PropertyMock, return_value=True
        ):
            with patch.object(scheduler._scheduler, "start") as mock_start:
                scheduler.start()

        mock_start.assert_not_called()


class TestSourceSchedulerCrawlSource:
    """Tests for _crawl_source()."""

    @pytest.fixture
    def scheduler(self):
        """Create SourceScheduler instance."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        return SourceScheduler(
            registry=mock_registry,
            on_items_discovered=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_crawl_source_disabled_source(self, scheduler):
        """Test _crawl_source skips disabled sources."""
        mock_source = MagicMock()
        mock_source.enabled = False

        scheduler._registry.get_source.return_value = mock_source

        await scheduler._crawl_source("source-1")

        scheduler._registry.get_parser.assert_not_called()

    @pytest.mark.asyncio
    async def test_crawl_source_no_parser(self, scheduler):
        """Test _crawl_source handles missing parser."""
        mock_source = MagicMock()
        mock_source.enabled = True
        mock_source.source_type = "rss"

        scheduler._registry.get_source.return_value = mock_source
        scheduler._registry.get_parser.return_value = None

        await scheduler._crawl_source("source-1")

        scheduler._registry.get_parser.assert_called_once_with("rss")

    @pytest.mark.asyncio
    async def test_crawl_source_parses_and_calls_callback(self, scheduler):
        """Test _crawl_source parses and calls callback."""
        from modules.ingestion.domain.models import NewsItem

        mock_source = MagicMock()
        mock_source.enabled = True
        mock_source.source_type = "rss"
        mock_source.id = "source-1"

        mock_parser = MagicMock()
        mock_item = MagicMock(spec=NewsItem)
        mock_parser.parse = AsyncMock(return_value=[mock_item])

        scheduler._registry.get_source.return_value = mock_source
        scheduler._registry.get_parser.return_value = mock_parser

        await scheduler._crawl_source("source-1", max_items=10)

        mock_parser.parse.assert_called_once_with(mock_source, force=False)
        scheduler._on_items.assert_called_once()

    @pytest.mark.asyncio
    async def test_atom_source_is_actually_crawled(self):
        """An 'atom' source must resolve to a parser against a real registry.

        Regression guard: get_parser() is an exact dict lookup, so when only
        the "rss" key was registered every atom source hit no_parser_for_type
        and was silently skipped on every scheduled run.
        """
        from modules.ingestion.domain.models import NewsItem, SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=MagicMock())
        config = SourceConfig(
            id="atom-src",
            name="Atom Source",
            url="https://example.com/feed.atom",
            source_type="atom",
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(registry=registry, on_items_discovered=on_items)

        expected = [MagicMock(spec=NewsItem)]
        with patch.object(
            registry.get_parser("atom"), "parse", new=AsyncMock(return_value=expected)
        ):
            await scheduler._crawl_source("atom-src")

        on_items.assert_called_once()
        assert on_items.call_args[0][0] == expected

    @pytest.mark.asyncio
    async def test_crawl_source_handles_exception(self, scheduler):
        """Test _crawl_source handles exceptions."""
        mock_source = MagicMock()
        mock_source.enabled = True
        mock_source.source_type = "rss"

        mock_parser = MagicMock()
        mock_parser.parse = AsyncMock(side_effect=Exception("Parse error"))

        scheduler._registry.get_source.return_value = mock_source
        scheduler._registry.get_parser.return_value = mock_parser

        # Should not raise
        await scheduler._crawl_source("source-1")


class TestSourceSchedulerTriggerNow:
    """Tests for trigger_now()."""

    @pytest.fixture
    def scheduler(self):
        """Create SourceScheduler instance."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        return SourceScheduler(
            registry=mock_registry,
            on_items_discovered=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_trigger_now_calls_crawl_source(self, scheduler):
        """Test trigger_now() calls _crawl_source."""
        scheduler._crawl_source = AsyncMock()

        await scheduler.trigger_now("source-1", max_items=5, task_id=None)

        scheduler._crawl_source.assert_called_once_with("source-1", 5, None, force=False)


class TestCrawlSourcePersistsValidators:
    """ETag/Last-Modified refreshed by parsers must reach the repo.

    update_crawl_state accepts etag/last_modified, but _crawl_source never
    passed them — RSSParser's conditional-fetch validators were mutated on
    the in-memory config only and lost on restart, silently downgrading
    every feed to full re-downloads.
    """

    def _make(self, items):
        from modules.ingestion.domain.models import NewsItem, SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        config = SourceConfig(
            id="src-1",
            name="S",
            url="https://example.com/feed",
            source_type="rss",
            etag='"etag-1"',
            last_modified="Wed, 01 Jan 2026 00:00:00 GMT",
        )
        registry = SourceRegistry(fetcher=MagicMock())
        registry.add_source(config)
        parser = MagicMock()
        parser.parse = AsyncMock(return_value=items)
        registry.get_parser = MagicMock(return_value=parser)

        repo = MagicMock()
        repo.update_crawl_state = AsyncMock()
        on_items = AsyncMock()
        scheduler = SourceScheduler(registry=registry, on_items_discovered=on_items, repo=repo)
        return scheduler, repo, config

    @pytest.mark.asyncio
    async def test_validators_persisted_with_items(self):
        from modules.ingestion.domain.models import NewsItem

        scheduler, repo, config = self._make([MagicMock(spec=NewsItem)])
        await scheduler._crawl_source("src-1")

        repo.update_crawl_state.assert_called_once()
        kwargs = repo.update_crawl_state.call_args.kwargs
        assert kwargs["etag"] == '"etag-1"'
        assert kwargs["last_modified"] == "Wed, 01 Jan 2026 00:00:00 GMT"
        assert kwargs.get("last_crawl_time") is not None

    @pytest.mark.asyncio
    async def test_validators_persisted_without_items(self):
        """A 304/empty crawl still persists validators (source is healthy)."""
        scheduler, repo, _ = self._make([])
        await scheduler._crawl_source("src-1")

        repo.update_crawl_state.assert_called_once()
        kwargs = repo.update_crawl_state.call_args.kwargs
        assert kwargs["etag"] == '"etag-1"'

    @pytest.mark.asyncio
    async def test_validators_refreshed_by_parser_are_persisted(self):
        """Values the parser writes back (not just initially stored) persist."""
        from modules.ingestion.domain.models import NewsItem, SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        config = SourceConfig(
            id="src-1", name="S", url="https://example.com/feed", source_type="rss"
        )
        registry = SourceRegistry(fetcher=MagicMock())
        registry.add_source(config)

        async def parse(source, force=False):
            source.etag = '"etag-fresh"'
            return [MagicMock(spec=NewsItem)]

        parser = MagicMock()
        parser.parse = AsyncMock(side_effect=parse)
        registry.get_parser = MagicMock(return_value=parser)

        repo = MagicMock()
        repo.update_crawl_state = AsyncMock()
        scheduler = SourceScheduler(registry=registry, on_items_discovered=AsyncMock(), repo=repo)
        await scheduler._crawl_source("src-1")

        assert repo.update_crawl_state.call_args.kwargs["etag"] == '"etag-fresh"'


class TestCrawlSourceReliability:
    """Timeout wrapper, failure backoff, and disable observability."""

    def _scheduler_with_parser(self, parse_behavior):
        from modules.ingestion.domain.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        config = SourceConfig(
            id="src-1", name="S", url="https://example.com/feed", source_type="rss"
        )
        registry = SourceRegistry(fetcher=MagicMock())
        registry.add_source(config)
        parser = MagicMock()
        parser.parse = AsyncMock(side_effect=parse_behavior)
        registry.get_parser = MagicMock(return_value=parser)
        return SourceScheduler(
            registry=registry, on_items_discovered=AsyncMock(), repo=None
        ), config

    @pytest.mark.asyncio
    async def test_hanging_parse_is_cut_off_by_timeout(self):
        """A parser that never returns is cut off at the crawl timeout."""

        async def hang(source, force=False):
            await asyncio.sleep(3600)

        scheduler, _ = self._scheduler_with_parser(hang)
        scheduler._crawl_timeout = 0.05

        await asyncio.wait_for(scheduler._crawl_source("src-1"), timeout=5)

        # Failure was recorded (the timeout counts as a crawl failure).
        assert scheduler._consecutive_failures.get("src-1") == 1

    @pytest.mark.asyncio
    async def test_repeated_failures_push_next_run_back(self):
        """Consecutive failures back off the source's next scheduled run."""
        from datetime import datetime as dt

        def boom(source, force=False):
            raise RuntimeError("boom")

        scheduler, config = self._scheduler_with_parser(boom)
        now = dt.now(tz=UTC)
        pushed = now + timedelta(minutes=60)
        scheduler._scheduler.modify_job = MagicMock()
        scheduler._next_backoff_time = MagicMock(return_value=pushed)

        await scheduler._crawl_source("src-1")
        await scheduler._crawl_source("src-1")

        # Second failure must have asked the scheduler to delay the job.
        scheduler._scheduler.modify_job.assert_called_once()
        kwargs = scheduler._scheduler.modify_job.call_args.kwargs
        assert kwargs["next_run_time"] == pushed

    @pytest.mark.asyncio
    async def test_auto_disable_increments_metric(self):
        """Auto-disable is observable, not silent."""
        from core.observability.metrics import MetricsCollector

        async def boom(source, force=False):
            raise RuntimeError("boom")

        scheduler, config = self._scheduler_with_parser(boom)
        scheduler._max_consecutive_failures = 1

        counter = MetricsCollector.source_auto_disabled_total.labels(source_id="src-1")
        before = counter._value.get()
        await scheduler._crawl_source("src-1")

        after = counter._value.get()
        assert after == before + 1


class TestConsecutiveEmptyYield:
    """Zero-yield sources (reachable but 0 items) get their own counter.

    A permanently empty source (e.g. newsnow-freebuf returning an empty
    items list) used to reset the failure counter every round and never
    triggered any warning. These tests pin the dedicated empty-yield logic.
    """

    @pytest.fixture
    def scheduler(self):
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        return SourceScheduler(
            registry=MagicMock(),
            on_items_discovered=AsyncMock(),
        )

    def _ok_source(self, scheduler, items):
        source = MagicMock()
        source.id = "src-empty"
        source.enabled = True
        source.source_type = "rss"
        scheduler._registry.get_source.return_value = source
        parser = MagicMock()
        parser.parse = AsyncMock(return_value=items)
        scheduler._registry.get_parser.return_value = parser
        scheduler._repo = MagicMock()
        scheduler._repo.update_crawl_state = AsyncMock()
        return source

    @pytest.mark.asyncio
    async def test_empty_yield_increments_counter_and_warns_at_threshold(self, scheduler):
        self._ok_source(scheduler, [])
        for i in range(scheduler._max_consecutive_empty):
            await scheduler._crawl_source("src-empty")
            assert scheduler._consecutive_empty["src-empty"] == i + 1

        assert scheduler._consecutive_empty["src-empty"] == scheduler._max_consecutive_empty

    @pytest.mark.asyncio
    async def test_nonempty_yield_resets_counter(self, scheduler):
        from modules.ingestion.domain.models import NewsItem

        item = NewsItem(
            url="https://x/1", title="t", source="s", source_host="x", source_id="src-empty"
        )
        self._ok_source(scheduler, [item])

        await scheduler._crawl_source("src-empty")
        assert "src-empty" not in scheduler._consecutive_empty

    @pytest.mark.asyncio
    async def test_failure_resets_empty_counter(self, scheduler):
        source = MagicMock()
        source.id = "src-empty"
        source.enabled = True
        source.source_type = "rss"
        scheduler._registry.get_source.return_value = source
        parser = MagicMock()
        parser.parse = AsyncMock(return_value=[])
        scheduler._registry.get_parser.return_value = parser
        scheduler._repo = MagicMock()
        scheduler._repo.update_crawl_state = AsyncMock()

        await scheduler._crawl_source("src-empty")
        assert scheduler._consecutive_empty.get("src-empty") == 1

        parser.parse = AsyncMock(side_effect=RuntimeError("boom"))
        await scheduler._crawl_source("src-empty")
        assert "src-empty" not in scheduler._consecutive_empty

    @pytest.mark.asyncio
    async def test_default_threshold_is_six(self, scheduler):
        assert scheduler._max_consecutive_empty == 6


class TestIntervalJitter:
    """Interval triggers carry jitter = min(interval*60*0.15, 300s).

    225+ sources share one 30-minute interval; without jitter they fire in
    lockstep after every scheduler restart (60 newsnow sources on one host).
    """

    @pytest.fixture
    def scheduler(self):
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        scheduler = SourceScheduler(
            registry=MagicMock(),
            on_items_discovered=AsyncMock(),
        )
        scheduler._scheduler = MagicMock()
        return scheduler

    def _source(self, interval_minutes: int):
        source = MagicMock()
        source.id = "src-j"
        source.enabled = True
        source.interval_minutes = interval_minutes
        return source

    def test_30min_interval_gets_270s_jitter(self, scheduler):
        scheduler._schedule_source(self._source(30))
        kwargs = scheduler._scheduler.add_job.call_args.kwargs
        assert kwargs["jitter"] == 270

    def test_long_interval_jitter_capped_at_300s(self, scheduler):
        scheduler._schedule_source(self._source(120))
        kwargs = scheduler._scheduler.add_job.call_args.kwargs
        assert kwargs["jitter"] == 300

    def test_jitter_is_positive_for_short_interval(self, scheduler):
        scheduler._schedule_source(self._source(5))
        kwargs = scheduler._scheduler.add_job.call_args.kwargs
        assert kwargs["jitter"] == 45


class TestUnscheduleCleansEmptyCounters:
    """R-ingestion-scheduling-001: removing a source's job must not leave
    stale zero-yield counters (a recreated id would inherit the old count)."""

    @pytest.fixture
    def scheduler(self):
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        scheduler = SourceScheduler(
            registry=MagicMock(),
            on_items_discovered=AsyncMock(),
        )
        scheduler._scheduler = MagicMock()
        return scheduler

    def test_unschedule_source_clears_empty_tracking(self, scheduler):
        scheduler._consecutive_empty["src-gone"] = 3
        scheduler._empty_warned.add("src-gone")

        scheduler.unschedule_source("src-gone")

        assert "src-gone" not in scheduler._consecutive_empty
        assert "src-gone" not in scheduler._empty_warned
