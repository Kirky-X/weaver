# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Source scheduler for periodic crawling using APScheduler."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.observability import get_logger
from modules.ingestion.domain.models import NewsItem, SourceConfig
from modules.ingestion.parsing.registry import SourceRegistry

if TYPE_CHECKING:
    from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo

log = get_logger(__name__)

# After this many consecutive failures, auto-disable the source
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5


class SourceScheduler:
    """Schedules periodic source parsing using APScheduler.

    Args:
        registry: Source registry with source configurations.
        on_items_discovered: Callback invoked with newly discovered items.
        repo: Optional repo for persisting crawl state (last_crawl_time etc).
        max_consecutive_failures: Threshold for auto-disabling a source.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        on_items_discovered: Callable[
            [list[NewsItem], SourceConfig, uuid.UUID | None, bool], Coroutine[Any, Any, None]
        ],
        repo: SourceConfigRepo | None = None,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        self._registry = registry
        self._on_items = on_items_discovered
        self._repo = repo
        self._max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures: dict[str, int] = {}
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Start scheduling all enabled sources."""
        for source in self._registry.list_sources(enabled_only=True):
            self._schedule_source(source)
        self._scheduler.start()
        log.info("source_scheduler_started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._scheduler.shutdown(wait=False)
        log.info("source_scheduler_stopped")

    def list_enabled_sources(self) -> list[SourceConfig]:
        """Get list of all enabled source configurations.

        Returns:
            List of SourceConfig objects for enabled sources.
        """
        return self._registry.list_sources(enabled_only=True)

    def _schedule_source(self, source: SourceConfig) -> None:
        """Schedule periodic parsing for a single source."""
        self._scheduler.add_job(
            self._crawl_source,
            "interval",
            minutes=source.interval_minutes,
            args=[source.id, None, None],
            id=f"source_{source.id}",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        log.debug("source_scheduled", source_id=source.id, interval=source.interval_minutes)

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
            items = await parser.parse(source, force=force)
            if items:
                source.last_crawl_time = datetime.now(UTC)
                # Persist last_crawl_time to database
                if self._repo and source.last_crawl_time:
                    try:
                        await self._repo.update_crawl_state(
                            source_id=source.id,
                            last_crawl_time=source.last_crawl_time,
                        )
                    except Exception as repo_exc:
                        log.warning(
                            "persist_crawl_state_failed",
                            source_id=source_id,
                            error=str(repo_exc),
                        )
                await self._on_items(items, source, max_items, task_id, force)
                # Reset consecutive failure counter on success
                self._consecutive_failures.pop(source_id, None)
                log.info(
                    "source_crawled",
                    source_id=source_id,
                    items_found=len(items),
                    max_items=max_items,
                )
            else:
                # No new items is not a failure — reset counter
                self._consecutive_failures.pop(source_id, None)
                log.debug("source_no_new_items", source_id=source_id)
        except Exception as exc:
            import traceback

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

            # Auto-disable source when threshold exceeded
            if failure_count >= self._max_consecutive_failures:
                await self._auto_disable_source(source, failure_count)

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

        # Remove scheduled job
        job_id = f"source_{source.id}"
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass  # Job may not exist

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

        log.warning(
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
