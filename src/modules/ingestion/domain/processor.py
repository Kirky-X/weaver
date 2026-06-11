# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Discovery processor for handling discovered items."""

from __future__ import annotations

import uuid
from typing import Any

from core.observability import get_logger
from modules.ingestion.crawling import Crawler
from modules.ingestion.deduplication import Deduplicator, SimHashDeduplicator, TitleItem
from modules.ingestion.fetching.exceptions import FetchError
from modules.processing.queue import ProcessingQueue
from modules.storage import ArticleRepo

log = get_logger(__name__)


class DiscoveryProcessor:
    """Processor for handling discovered news items.

    Handles the data flow:
    RSS → URL Deduplicator → SimHash Deduplicator → Crawler → ProcessingQueue

    This class is extracted from Container to improve separation of concerns.
    """

    def __init__(
        self,
        crawler: Crawler,
        article_repo: ArticleRepo,
        deduplicator: Deduplicator | None = None,
        simhash_dedup: SimHashDeduplicator | None = None,
        processing_queue: ProcessingQueue | None = None,
        enable_simhash: bool = True,
    ) -> None:
        """Initialize the processor.

        Args:
            crawler: Crawler for fetching article content.
            article_repo: Repository for saving articles.
            deduplicator: Optional deduplicator for URL filtering.
            simhash_dedup: Optional SimHash deduplicator for title filtering.
            processing_queue: Optional queue for async processing.
            enable_simhash: Whether to enable SimHash deduplication.
        """
        self._crawler = crawler
        self._article_repo = article_repo
        self._deduplicator = deduplicator
        self._simhash_dedup = simhash_dedup
        self._processing_queue = processing_queue
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

    async def on_items_discovered(
        self,
        items: list[Any],
        source: Any,
        max_items: int | None = None,
        task_id: uuid.UUID | None = None,
        force: bool = False,
    ) -> None:
        """Handle callback to save discovered items to database and enqueue for processing.

        Deduplication flow:
        1. URL deduplication (exact match, skipped when force=True)
        2. Title SimHash deduplication (similarity match)
        3. Crawler fetch
        4. Enqueue to processing queue (soft backpressure if full)

        Args:
            items: List of discovered news items.
            source: Source configuration.
            max_items: Maximum number of items to process (None for unlimited).
            task_id: Optional task ID for tracking.
            force: Force re-crawl, skip URL dedup (still apply simhash for content quality).
        """
        import traceback

        log.info("items_discovered", count=len(items), source=source.id, max_items=max_items)

        try:
            # Stage 1: URL deduplication (skip when force=True to reprocess existing URLs)
            if self._deduplicator and not force:
                items = await self._deduplicator.dedup(items)
                if not items:
                    log.info("all_items_deduplicated_by_url", source=source.id)
                    return
                log.info("items_after_url_dedup", count=len(items), source=source.id)
            elif force:
                log.info("url_dedup_skipped_force_mode", count=len(items), source=source.id)

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

            from modules.ingestion.domain.models import RawArticle

            successful_articles = [a for a in raw_articles if isinstance(a, RawArticle)]
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

            if article_ids and self._processing_queue:
                for idx, aid in enumerate(article_ids):
                    success = await self._processing_queue.enqueue(
                        str(aid),
                        task_id=str(task_id) if task_id else None,
                    )
                    if not success:
                        log.warning(
                            "queue_full_articles_skipped",
                            queued=idx,
                            skipped=len(article_ids) - idx,
                        )
                        break
                log.info("articles_enqueued", count=len(article_ids))
        except Exception as exc:
            log.error(
                "on_items_discovered_failed",
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            raise
