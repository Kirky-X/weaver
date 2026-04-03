# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Discovery processor for handling discovered items."""

from __future__ import annotations

import uuid
from typing import Any

from core.observability.logging import get_logger
from modules.ingestion.crawling import Crawler
from modules.ingestion.deduplication import Deduplicator, SimHashDeduplicator, TitleItem
from modules.ingestion.fetching.exceptions import FetchError
from modules.processing.pipeline.graph import Pipeline
from modules.storage import ArticleRepo

log = get_logger("discovery_processor")


class DiscoveryProcessor:
    """Processor for handling discovered news items.

    Handles the data flow:
    RSS → URL Deduplicator → SimHash Deduplicator → Crawler → Pipeline

    This class is extracted from Container to improve separation of concerns.
    """

    def __init__(
        self,
        crawler: Crawler,
        article_repo: ArticleRepo,
        deduplicator: Deduplicator | None = None,
        simhash_dedup: SimHashDeduplicator | None = None,
        pipeline: Pipeline | None = None,
        enable_simhash: bool = True,
    ) -> None:
        """Initialize the processor.

        Args:
            crawler: Crawler for fetching article content.
            article_repo: Repository for saving articles.
            deduplicator: Optional deduplicator for URL filtering.
            simhash_dedup: Optional SimHash deduplicator for title filtering.
            pipeline: Optional pipeline for processing articles.
            enable_simhash: Whether to enable SimHash deduplication.
        """
        self._crawler = crawler
        self._article_repo = article_repo
        self._deduplicator = deduplicator
        self._simhash_dedup = simhash_dedup
        self._pipeline = pipeline
        self._enable_simhash = enable_simhash

    def set_deduplicator(self, deduplicator: Deduplicator) -> None:
        """Set the deduplicator.

        Args:
            deduplicator: Deduplicator instance.
        """
        self._deduplicator = deduplicator

    def set_simhash_dedup(self, simhash_dedup: SimHashDeduplicator) -> None:
        """Set the SimHash deduplicator.

        Args:
            simhash_dedup: SimHashDeduplicator instance.
        """
        self._simhash_dedup = simhash_dedup

    def set_enable_simhash(self, enable: bool) -> None:
        """Enable or disable SimHash deduplication.

        Args:
            enable: Whether to enable SimHash.
        """
        self._enable_simhash = enable

    def set_pipeline(self, pipeline: Pipeline) -> None:
        """Set the pipeline for processing.

        Args:
            pipeline: Pipeline instance.
        """
        self._pipeline = pipeline

    async def on_items_discovered(
        self,
        items: list[Any],
        source: Any,
        max_items: int | None = None,
        task_id: uuid.UUID | None = None,
    ) -> None:
        """Handle callback to save discovered items to database and trigger pipeline.

        Deduplication flow:
        1. URL deduplication (exact match)
        2. Title SimHash deduplication (similarity match)
        3. Crawler fetch

        Args:
            items: List of discovered news items.
            source: Source configuration.
            max_items: Maximum number of items to process (None for unlimited).
            task_id: Optional task ID for tracking.
        """
        import traceback

        log.info("items_discovered", count=len(items), source=source.id, max_items=max_items)

        try:
            # Stage 1: URL deduplication
            if self._deduplicator:
                items = await self._deduplicator.dedup(items)
                if not items:
                    log.info("all_items_deduplicated_by_url", source=source.id)
                    return
                log.info("items_after_url_dedup", count=len(items), source=source.id)

            # Stage 2: Title SimHash deduplication
            if self._enable_simhash and self._simhash_dedup and items:
                # Convert items to TitleItem format
                title_items = []
                for item in items:
                    title = getattr(item, "title", None) or getattr(item, "name", "")
                    if title:
                        title_items.append(TitleItem(url=item.url, title=title))

                if title_items:
                    (
                        unique_items,
                        filtered_count,
                    ) = await self._simhash_dedup.dedup_titles_with_metrics(title_items)
                    # Filter original items based on unique titles
                    unique_urls = {item.url for item in unique_items}
                    items = [item for item in items if item.url in unique_urls]

                    if not items:
                        log.info("all_items_deduplicated_by_simhash", source=source.id)
                        return
                    log.info(
                        "items_after_simhash_dedup",
                        count=len(items),
                        filtered=filtered_count,
                        source=source.id,
                    )

            if max_items is not None and len(items) > max_items:
                items = items[:max_items]
                log.info("items_limited", count=len(items), max_items=max_items)

            raw_articles = await self._crawler.crawl_batch(items)
            log.info("crawl_complete", count=len(raw_articles))

            from modules.ingestion.domain.models import ArticleRaw

            successful_articles = [a for a in raw_articles if isinstance(a, ArticleRaw)]
            errors = [e for e in raw_articles if isinstance(e, FetchError)]

            if errors:
                for error in errors:
                    log.warning(
                        "crawl_item_failed",
                        url=error.url,
                        message=error.message,
                        cause=str(error.cause) if error.cause else None,
                    )

            if not successful_articles:
                log.warning("no_articles_crawled", source=source.id)
                return

            article_ids = []
            for article in successful_articles:
                try:
                    article_id = await self._article_repo.insert_raw(article, task_id=task_id)
                    article_ids.append(article_id)
                except Exception as exc:
                    log.error("insert_raw_failed", url=article.url, error=str(exc))

            if article_ids and self._pipeline:
                try:
                    await self._pipeline.process_batch(
                        successful_articles,
                        article_ids=article_ids,
                        task_id=task_id,
                    )
                    log.info("pipeline_batch_processed", count=len(successful_articles))
                except Exception as exc:
                    log.error(
                        "pipeline_process_failed", error=str(exc), traceback=traceback.format_exc()
                    )
        except Exception as exc:
            log.error(
                "on_items_discovered_failed",
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            raise
