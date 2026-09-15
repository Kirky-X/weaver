# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Pipeline service implementation."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from core.observability import get_logger

log = get_logger(__name__)


class PipelineServiceImpl:
    """Implementation of PipelineService that wraps Pipeline with a stable interface.

    This service provides a public API for pipeline operations, hiding internal
    implementation details like PipelineState management.

    Implements: PipelineService
    """

    def __init__(self, pipeline: Any, crawler: Any | None = None) -> None:
        """Initialize with a Pipeline instance.

        Args:
            pipeline: The Pipeline instance to wrap.
            crawler: Optional Crawler used by ``run_full_pipeline`` to fetch
                the URL before processing. Required only when callers invoke
                ``run_full_pipeline``.
        """
        self._pipeline = pipeline
        self._crawler = crawler

    async def run_phase3_per_article(
        self,
        article_id: str,
        *,
        force_reprocess: bool = False,
    ) -> dict[str, Any]:
        """Run phase 3 processing for a single article.

        Args:
            article_id: The article ID to process.
            force_reprocess: Force reprocessing even if already processed.

        Returns:
            Processing result with entity extraction status.

        Raises:
            ArticleNotFoundError: If article does not exist.
            ProcessingError: If processing fails.
        """
        log.info("run_phase3_per_article", article_id=article_id, force_reprocess=force_reprocess)

        # Delegate to pipeline's public method
        # The pipeline should expose a public interface for this operation
        result = await self._pipeline.process_article_phase3(
            article_id=article_id,
            force_reprocess=force_reprocess,
        )
        return result

    async def get_pipeline_status(self, article_id: str) -> dict[str, Any]:
        """Get the processing status for an article.

        Args:
            article_id: The article ID to check.

        Returns:
            Status dict with phase completion flags.
        """
        log.debug("get_pipeline_status", article_id=article_id)
        return await self._pipeline.get_article_status(article_id)

    async def run_full_pipeline(
        self,
        url: str,
        *,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        """Run the complete pipeline for a URL.

        Args:
            url: URL to process.
            source_name: Optional source name override.

        Returns:
            Processing result with article ID and status.
        """
        log.info("run_full_pipeline", url=url, source_name=source_name)

        if self._crawler is None:
            raise RuntimeError(
                "Crawler not configured. Pass a crawler to PipelineServiceImpl "
                "to use run_full_pipeline()."
            )

        from modules.ingestion.fetching.exceptions import FetchError
        from core.types.ingestion_models import NewsItem

        item = NewsItem(
            url=url,
            title="",
            source=source_name or "url_endpoint",
            source_host=urlparse(url).netloc,
        )
        results = await self._crawler.crawl_batch([item])
        if results and isinstance(results[0], FetchError):
            raise results[0]
        if not results:
            raise RuntimeError(f"Crawler returned no results for {url}")

        states = await self._pipeline.process_batch([results[0]])
        return states[0] if states else {}
