# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Background consumer for processing queue."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.observability import get_logger
from modules.processing.queue import QUEUE_KEY, ProcessingQueue

if TYPE_CHECKING:
    from config.subconfigs import PipelineProcessSettings
    from modules.processing.pipeline.graph import Pipeline
    from modules.storage.postgres.article_repo import ArticleRepo

log = get_logger(__name__)


class PipelineWorker:
    """Consumer that processes articles from queue.

    Runs as asyncio.Task in current process. Pulls from Redis queue,
    reconstructs articles from DB, calls pipeline.process_batch().
    """

    def __init__(
        self,
        queue: ProcessingQueue,
        pipeline: Pipeline,
        article_repo: ArticleRepo,
        pipeline_settings: PipelineProcessSettings,
    ) -> None:
        self._queue = queue
        self._pipeline = pipeline
        self._article_repo = article_repo
        self._settings = pipeline_settings
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start consumer loop."""
        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        log.info("pipeline_worker_started", queue_key=QUEUE_KEY)

    async def stop(self) -> None:
        """Stop consumer gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("pipeline_worker_stopped")

    async def _consume_loop(self) -> None:
        """Main consumer loop: dequeue -> reconstruct -> process."""
        while self._running:
            try:
                items = await self._queue.dequeue_batch(self._settings.worker_batch_size)
                if not items:
                    await asyncio.sleep(self._settings.worker_poll_interval)
                    continue

                article_ids = [item[0] for item in items]
                task_id = items[0][1]  # Use first task_id for batch

                # Reconstruct RawArticle from DB
                articles = await self._article_repo.get_by_ids(article_ids)
                if not articles:
                    log.warning("articles_not_found", ids=article_ids)
                    continue

                # Process batch
                await self._pipeline.process_batch(
                    articles,
                    article_ids=article_ids,
                    task_id=task_id,
                )
                log.info(
                    "batch_processed", count=len(articles), queue_len=await self._queue.length()
                )

            except asyncio.CancelledError:
                log.info("worker_cancelled")
                raise

            except Exception as e:
                log.error("worker_error", error=str(e), exc_info=True)
                await asyncio.sleep(self._settings.worker_error_delay)

    async def drain(self) -> None:
        """Process remaining queue items (for shutdown)."""
        while True:
            items = await self._queue.dequeue_batch(self._settings.worker_batch_size)
            if not items:
                break

            article_ids = [item[0] for item in items]
            articles = await self._article_repo.get_by_ids(article_ids)
            if articles:
                await self._pipeline.process_batch(articles, article_ids=article_ids)
                log.info("drain_processed", count=len(articles))
