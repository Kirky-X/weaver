# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pipeline service implementation."""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger

log = get_logger("pipeline_service")


class PipelineServiceImpl:
    """Implementation of PipelineService that wraps Pipeline with a stable interface.

    This service provides a public API for pipeline operations, hiding internal
    implementation details like PipelineState management.

    Implements: PipelineService
    """

    def __init__(self, pipeline: Any) -> None:
        """Initialize with a Pipeline instance.

        Args:
            pipeline: The Pipeline instance to wrap.
        """
        self._pipeline = pipeline

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
        result = await self._pipeline.run(url=url, source_name=source_name)
        return result
