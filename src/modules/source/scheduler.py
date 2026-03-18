# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Source scheduler for periodic crawling using APScheduler."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.observability.logging import get_logger
from modules.source.models import NewsItem, SourceConfig
from modules.source.registry import SourceRegistry

log = get_logger("source_scheduler")


class SourceScheduler:
    """Schedules periodic source parsing using APScheduler.

    Args:
        registry: Source registry with source configurations.
        on_items_discovered: Callback invoked with newly discovered items.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        on_items_discovered: Callable[
            [list[NewsItem], SourceConfig, uuid.UUID | None], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self._registry = registry
        self._on_items = on_items_discovered
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
        self, source_id: str, max_items: int | None = None, task_id: uuid.UUID | None = None
    ) -> None:
        """Execute a single crawl for one source.

        Args:
            source_id: The source ID to crawl.
            max_items: Maximum number of items to process.
            task_id: Optional task ID for tracking.
        """
        source = self._registry.get_source(source_id)
        if not source or not source.enabled:
            return

        parser = self._registry.get_parser(source.source_type)
        if not parser:
            log.warning("no_parser_for_type", source_type=source.source_type)
            return

        try:
            items = await parser.parse(source)
            if items:
                source.last_crawl_time = datetime.now(UTC)
                await self._on_items(items, source, max_items, task_id)
                log.info(
                    "source_crawled",
                    source_id=source_id,
                    items_found=len(items),
                    max_items=max_items,
                )
            else:
                log.debug("source_no_new_items", source_id=source_id)
        except Exception as exc:
            import traceback

            log.error(
                "source_crawl_failed",
                source_id=source_id,
                error=str(exc),
                traceback=traceback.format_exc(),
            )

    async def trigger_now(
        self, source_id: str, max_items: int | None = None, task_id: uuid.UUID | None = None
    ) -> None:
        """Trigger an immediate crawl for a source.

        Args:
            source_id: The source ID to crawl.
            max_items: Maximum number of items to process.
            task_id: Optional task ID for tracking.
        """
        await self._crawl_source(source_id, max_items, task_id)
