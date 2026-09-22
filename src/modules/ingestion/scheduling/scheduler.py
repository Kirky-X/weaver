# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Source scheduler for periodic crawling using APScheduler."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.observability import get_logger, MetricsCollector
from modules.ingestion.domain.models import NewsItem, SourceConfig
from modules.ingestion.parsing.registry import SourceRegistry

if TYPE_CHECKING:
    from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo

log = get_logger(__name__)

# After this many consecutive failures, auto-disable the source
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5
# After this many consecutive successful crawls yielding 0 items, warn once.
# A permanently empty source (API alive, items list always empty) never hits
# the failure path, so without this it would spin silently forever.
DEFAULT_MAX_CONSECUTIVE_EMPTY = 6
# Wall-clock cap for a single source parse. The fetcher has its own timeouts;
# this is the last line of defence against a hung parser blocking its slot.
DEFAULT_CRAWL_TIMEOUT_SECONDS = 300.0
# Backoff: next run pushed by interval * 2^(failures-1), capped here.
MAX_BACKOFF_MULTIPLIER = 8


class SourceScheduler:
    """Schedules periodic source parsing using APScheduler.

    Args:
        registry: Source registry with source configurations.
        on_items_discovered: Callback invoked with newly discovered items.
        repo: Optional repo for persisting crawl state (last_crawl_time etc).
        max_consecutive_failures: Threshold for auto-disabling a source.
        crawl_timeout: Per-crawl wall-clock timeout in seconds.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        on_items_discovered: Callable[
            [list[NewsItem], SourceConfig, uuid.UUID | None, bool], Coroutine[Any, Any, None]
        ],
        repo: SourceConfigRepo | None = None,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        max_consecutive_empty: int = DEFAULT_MAX_CONSECUTIVE_EMPTY,
        crawl_timeout: float = DEFAULT_CRAWL_TIMEOUT_SECONDS,
    ) -> None:
        self._registry = registry
        self._on_items = on_items_discovered
        self._repo = repo
        self._max_consecutive_failures = max_consecutive_failures
        self._max_consecutive_empty = max_consecutive_empty
        self._crawl_timeout = crawl_timeout
        self._consecutive_failures: dict[str, int] = {}
        self._consecutive_empty: dict[str, int] = {}
        self._empty_warned: set[str] = set()
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Start scheduling all enabled sources.

        Idempotent: a second call while already running is a no-op instead of
        raising ``SchedulerAlreadyRunningError``.
        """
        if self._scheduler.running:
            log.debug("source_scheduler_already_running")
            return
        for source in self._registry.list_sources(enabled_only=True):
            self._schedule_source(source)
        self._scheduler.start()
        log.info("source_scheduler_started")

    def register_source(self, source: Any) -> None:
        """Register a new source with the scheduler registry (public API)."""
        self._registry.add_source(source)

    def stop(self) -> None:
        """Stop the scheduler.

        Idempotent: stopping a scheduler that was never started (or has
        already been stopped) is a no-op instead of raising
        ``SchedulerNotRunningError``.
        """
        if not self._scheduler.running:
            log.debug("source_scheduler_stop_skipped_not_running")
            return
        self._scheduler.shutdown(wait=False)
        log.info("source_scheduler_stopped")

    def list_enabled_sources(self) -> list[SourceConfig]:
        """Get list of all enabled source configurations.

        Returns:
            List of SourceConfig objects for enabled sources.
        """
        return self._registry.list_sources(enabled_only=True)

    def schedule_source(self, source: SourceConfig) -> None:
        """Schedule (or reschedule) periodic crawling for one source at runtime.

        Public counterpart of ``_schedule_source``: callers that create or
        update a source after ``start()`` must invoke this so the source is
        actually crawled on its interval. No-op when the scheduler has not
        been started yet (``start()`` will schedule it).

        Args:
            source: Source configuration to schedule.
        """
        if not self._scheduler.running:
            log.debug(
                "source_schedule_skipped_scheduler_not_running",
                source_id=source.id,
            )
            return
        self._schedule_source(source)

    def unschedule_source(self, source_id: str) -> None:
        """Remove the periodic job for a source (e.g. on delete/disable).

        Args:
            source_id: The source identifier.
        """
        try:
            self._scheduler.remove_job(f"source_{source_id}")
        except Exception as exc:
            # Job may never have been scheduled (created while stopped).
            log.debug(
                "source_unschedule_skipped",
                source_id=source_id,
                error=str(exc),
            )
        finally:
            # A recreated source id must start with a clean zero-yield slate.
            self._consecutive_empty.pop(source_id, None)
            self._empty_warned.discard(source_id)

    def _schedule_source(self, source: SourceConfig) -> None:
        """Schedule periodic parsing for a single source."""
        # Stagger triggers: 225+ sources sharing one interval would otherwise
        # fire in lockstep after every restart (crawling bursts, 60 newsnow
        # sources on one host). 15% of the interval, hard-capped at 5 minutes.
        jitter_seconds = min(int(source.interval_minutes * 60 * 0.15), 300)
        self._scheduler.add_job(
            self._crawl_source,
            "interval",
            minutes=source.interval_minutes,
            jitter=jitter_seconds,
            args=[source.id, None, None],
            id=f"source_{source.id}",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        log.debug(
            "source_scheduled",
            source_id=source.id,
            interval=source.interval_minutes,
            jitter_seconds=jitter_seconds,
        )

    async def _crawl_source(
        self,
        source_id: str,
        max_items: int | None = None,
        task_id: uuid.UUID | None = None,
        force: bool = False,
    ) -> None:
        """Execute a single crawl for one source.

        Args:
            source_id: The source ID to crawl.
            max_items: Maximum number of items to process.
            task_id: Optional task ID for tracking.
            force: Force re-crawl even for recently fetched URLs.
        """
        source = self._registry.get_source(source_id)
        if not source or not source.enabled:
            return

        parser = self._registry.get_parser(source.source_type)
        if not parser:
            log.warning("no_parser_for_type", source_type=source.source_type)
            return

        try:
            items = await asyncio.wait_for(
                parser.parse(source, force=force), timeout=self._crawl_timeout
            )
            # Persist crawl state in one shot. Validators (etag/last_modified)
            # are stored independent of whether items were produced, so a
            # 304-then-restart cycle keeps conditional-fetch capability (else
            # every poll after a restart re-downloads the full feed/page).
            if items:
                source.last_crawl_time = datetime.now(UTC)
            if self._repo and (items or source.etag or source.last_modified):
                try:
                    await self._repo.update_crawl_state(
                        source_id=source.id,
                        last_crawl_time=source.last_crawl_time if items else None,
                        etag=source.etag,
                        last_modified=source.last_modified,
                    )
                except Exception as repo_exc:
                    log.warning(
                        "persist_crawl_state_failed",
                        source_id=source_id,
                        error=str(repo_exc),
                    )
            if items:
                await self._on_items(items, source, max_items, task_id, force)
                # Reset consecutive failure counter on success
                self._consecutive_failures.pop(source_id, None)
                self._consecutive_empty.pop(source_id, None)
                self._empty_warned.discard(source_id)
                log.info(
                    "source_crawled",
                    source_id=source_id,
                    items_found=len(items),
                    max_items=max_items,
                )
            else:
                # No new items is not a failure — reset counter
                self._consecutive_failures.pop(source_id, None)
                self._track_empty_yield(source_id)
                log.debug("source_no_new_items", source_id=source_id)
        except Exception as exc:
            import traceback

            # A failing source is not an empty source: reset the empty
            # counter, failures have their own backoff/disable path.
            self._consecutive_empty.pop(source_id, None)
            self._empty_warned.discard(source_id)

            # Track consecutive failures
            self._consecutive_failures[source_id] = self._consecutive_failures.get(source_id, 0) + 1
            failure_count = self._consecutive_failures[source_id]

            log.error(
                "source_crawl_failed",
                source_id=source_id,
                error=str(exc),
                error_type=type(exc).__name__,
                consecutive_failures=failure_count,
                traceback=traceback.format_exc(),
            )

            # Back off the next scheduled run: a source that keeps failing
            # should not keep burning its slot at the normal interval.
            self._apply_failure_backoff(source_id, failure_count)

            # Auto-disable source when threshold exceeded
            if failure_count >= self._max_consecutive_failures:
                await self._auto_disable_source(source, failure_count)

    def _track_empty_yield(self, source_id: str) -> None:
        """Count a successful crawl that yielded 0 items; warn once at threshold.

        A permanently empty source never enters the failure path, so without
        this it would spin at full frequency forever with no signal.
        """
        count = self._consecutive_empty.get(source_id, 0) + 1
        self._consecutive_empty[source_id] = count
        if count >= self._max_consecutive_empty and source_id not in self._empty_warned:
            self._empty_warned.add(source_id)
            MetricsCollector.source_zero_yield_total.labels(source_id=source_id).inc()
            log.warning(
                "source_prolonged_zero_yield",
                source_id=source_id,
                consecutive_empty=count,
                threshold=self._max_consecutive_empty,
            )

    def _next_backoff_time(self, source_id: str, failure_count: int) -> datetime:
        """Compute the backoff next-run time after ``failure_count`` failures."""
        source = self._registry.get_source(source_id)
        interval = source.interval_minutes if source else 30
        multiplier = min(2 ** max(failure_count - 1, 0), MAX_BACKOFF_MULTIPLIER)
        return datetime.now(tz=UTC) + timedelta(minutes=interval * multiplier)

    def _apply_failure_backoff(self, source_id: str, failure_count: int) -> None:
        """Push the source job's next run back when failures accumulate."""
        if failure_count < 2:
            return
        try:
            self._scheduler.modify_job(
                f"source_{source_id}",
                next_run_time=self._next_backoff_time(source_id, failure_count),
            )
            log.info(
                "source_crawl_backoff",
                source_id=source_id,
                consecutive_failures=failure_count,
            )
        except Exception as exc:
            # Job may not exist (manual trigger_now with no scheduled job).
            log.debug(
                "source_backoff_skipped",
                source_id=source_id,
                error=str(exc),
            )

    async def _auto_disable_source(self, source: SourceConfig, failure_count: int) -> None:
        """Auto-disable a source after exceeding consecutive failure threshold.

        Sets source.enabled = False, removes its scheduled job, and persists
        the disabled state to the database.

        Args:
            source: Source configuration to disable.
            failure_count: Current consecutive failure count.
        """
        source.enabled = False
        self._consecutive_failures.pop(source.id, None)
        self._consecutive_empty.pop(source.id, None)
        self._empty_warned.discard(source.id)
        # Observability: auto-disable must not be silent — it silently
        # shrinks collection coverage until someone notices.
        MetricsCollector.source_auto_disabled_total.labels(source_id=source.id).inc()

        # Remove scheduled job (absence is expected for never-run sources)
        job_id = f"source_{source.id}"
        try:
            self._scheduler.remove_job(job_id)
        except Exception as exc:
            log.debug(
                "source_job_removal_skipped",
                job_id=job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        # Persist disabled state
        if self._repo:
            try:
                await self._repo.update_crawl_state(
                    source_id=source.id,
                    enabled=False,
                )
            except Exception as repo_exc:
                log.warning(
                    "persist_disabled_state_failed",
                    source_id=source.id,
                    error=str(repo_exc),
                )

        log.error(
            "source_auto_disabled",
            source_id=source.id,
            source_name=source.name,
            consecutive_failures=failure_count,
            threshold=self._max_consecutive_failures,
        )

    async def trigger_now(
        self,
        source_id: str,
        max_items: int | None = None,
        task_id: uuid.UUID | None = None,
        force: bool = False,
    ) -> None:
        """Trigger an immediate crawl for a source.

        Args:
            source_id: The source ID to crawl.
            max_items: Maximum number of items to process.
            task_id: Optional task ID for tracking.
            force: Force re-crawl even for recently fetched URLs.
        """
        await self._crawl_source(source_id, max_items, task_id, force=force)
