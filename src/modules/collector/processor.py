"""Discovery processor for handling discovered items."""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger
from modules.collector.crawler import Crawler
from modules.pipeline.graph import Pipeline
from modules.storage.article_repo import ArticleRepo

log = get_logger("discovery_processor")


class DiscoveryProcessor:
    """Processor for handling discovered news items.

    Handles the data flow:
    RSS → Deduplicator → Interleaver → Crawler → Pipeline

    This class is extracted from Container to improve separation of concerns.
    """

    def __init__(
        self,
        crawler: Crawler,
        article_repo: ArticleRepo,
        pipeline: Pipeline | None = None,
    ) -> None:
        """Initialize the processor.

        Args:
            crawler: Crawler for fetching article content.
            article_repo: Repository for saving articles.
            pipeline: Optional pipeline for processing articles.
        """
        self._crawler = crawler
        self._article_repo = article_repo
        self._pipeline = pipeline

    def set_pipeline(self, pipeline: Pipeline) -> None:
        """Set the pipeline for processing.

        Args:
            pipeline: Pipeline instance.
        """
        self._pipeline = pipeline

    async def on_items_discovered(self, items: list[Any], source: Any) -> None:
        """Callback to save discovered items to database and trigger pipeline.

        Args:
            items: List of discovered news items.
            source: Source configuration.
        """
        log.info("items_discovered", count=len(items), source=source.id)

        try:
            raw_articles = await self._crawler.crawl_batch(items)
            log.info("crawl_complete", count=len(raw_articles))
        except Exception as exc:
            log.error("crawl_failed", error=str(exc))
            return

        successful_articles = [a for a in raw_articles if not isinstance(a, Exception)]
        failed_count = len(raw_articles) - len(successful_articles)
        if failed_count > 0:
            log.warning("crawl_partial_failure", failed=failed_count)

        if not successful_articles:
            log.warning("no_articles_crawled", source=source.id)
            return

        article_ids = []
        for article in successful_articles:
            try:
                article_id = await self._article_repo.insert_raw(article)
                article_ids.append(article_id)
            except Exception as exc:
                log.error("insert_raw_failed", url=article.url, error=str(exc))

        if article_ids and self._pipeline:
            try:
                await self._pipeline.process_batch(successful_articles)
                log.info("pipeline_batch_processed", count=len(successful_articles))
            except Exception as exc:
                log.error("pipeline_process_failed", error=str(exc))
