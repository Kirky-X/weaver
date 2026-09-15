# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Integration tests for PipelineService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.pipeline_service import PipelineServiceImpl


@pytest.fixture
def mock_pipeline() -> MagicMock:
    """Create a mock Pipeline instance."""
    pipeline = MagicMock()
    pipeline.process_article_phase3 = AsyncMock(
        return_value={
            "article_id": "test-article-id",
            "status": "completed",
            "entities_extracted": 5,
        }
    )
    pipeline.get_article_status = AsyncMock(
        return_value={
            "article_id": "test-article-id",
            "phase1_completed": True,
            "phase2_completed": True,
            "phase3_completed": True,
        }
    )
    pipeline.process_batch = AsyncMock(
        return_value=[
            {
                "article_id": "test-article-id",
                "status": "completed",
            }
        ]
    )
    return pipeline


@pytest.fixture
def mock_crawler() -> MagicMock:
    """Create a mock Crawler whose crawl_batch returns a fetched article."""
    crawler = MagicMock()
    article = MagicMock()
    crawler.crawl_batch = AsyncMock(return_value=[article])
    return crawler


@pytest.fixture
def pipeline_service(mock_pipeline: MagicMock) -> PipelineServiceImpl:
    """Create a PipelineServiceImpl instance (no crawler)."""
    return PipelineServiceImpl(mock_pipeline)


@pytest.fixture
def pipeline_service_with_crawler(
    mock_pipeline: MagicMock, mock_crawler: MagicMock
) -> PipelineServiceImpl:
    """Create a PipelineServiceImpl instance with a crawler attached."""
    return PipelineServiceImpl(mock_pipeline, crawler=mock_crawler)


class TestPipelineServiceImpl:
    """Tests for PipelineServiceImpl."""

    async def test_run_phase3_per_article_delegates_to_pipeline(
        self,
        pipeline_service: PipelineServiceImpl,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test that run_phase3_per_article delegates to pipeline."""
        article_id = str(uuid.uuid4())

        result = await pipeline_service.run_phase3_per_article(
            article_id=article_id,
            force_reprocess=True,
        )

        # Verify delegation
        mock_pipeline.process_article_phase3.assert_called_once_with(
            article_id=article_id,
            force_reprocess=True,
        )

        # Verify result
        assert result["article_id"] == "test-article-id"
        assert result["status"] == "completed"

    async def test_get_pipeline_status_delegates_to_pipeline(
        self,
        pipeline_service: PipelineServiceImpl,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test that get_pipeline_status delegates to pipeline."""
        article_id = str(uuid.uuid4())

        result = await pipeline_service.get_pipeline_status(article_id)

        # Verify delegation
        mock_pipeline.get_article_status.assert_called_once_with(article_id)

        # Verify result
        assert result["phase1_completed"] is True
        assert result["phase2_completed"] is True
        assert result["phase3_completed"] is True

    async def test_run_full_pipeline_crawls_then_processes(
        self,
        pipeline_service_with_crawler: PipelineServiceImpl,
        mock_pipeline: MagicMock,
        mock_crawler: MagicMock,
    ) -> None:
        """Test that run_full_pipeline crawls the URL then runs process_batch."""
        url = "https://example.com/test"

        result = await pipeline_service_with_crawler.run_full_pipeline(
            url=url,
            source_name="test-source",
        )

        # Verify crawl happened with a NewsItem carrying the source
        mock_crawler.crawl_batch.assert_awaited_once()
        item = mock_crawler.crawl_batch.await_args.args[0][0]
        assert item.url == url
        assert item.source == "test-source"

        # Verify the fetched article went through process_batch
        mock_pipeline.process_batch.assert_awaited_once()
        assert (
            mock_pipeline.process_batch.await_args.args[0][0]
            is mock_crawler.crawl_batch.return_value[0]
        )

        # Verify result is the first pipeline state
        assert result["article_id"] == "test-article-id"

    async def test_run_full_pipeline_without_crawler_raises(
        self,
        pipeline_service: PipelineServiceImpl,
        mock_pipeline: MagicMock,
    ) -> None:
        """run_full_pipeline must fail fast when no crawler was injected."""
        with pytest.raises(RuntimeError, match="Crawler not configured"):
            await pipeline_service.run_full_pipeline("https://example.com/test")
        mock_pipeline.process_batch.assert_not_awaited()

    async def test_run_full_pipeline_fetch_error_raises(
        self,
        pipeline_service_with_crawler: PipelineServiceImpl,
        mock_crawler: MagicMock,
    ) -> None:
        """A FetchError from the crawler must propagate to the caller."""
        from modules.ingestion.fetching.exceptions import FetchError

        mock_crawler.crawl_batch = AsyncMock(
            return_value=[FetchError(url="https://example.com/test", message="blocked")]
        )

        with pytest.raises(FetchError):
            await pipeline_service_with_crawler.run_full_pipeline("https://example.com/test")

    async def test_run_full_pipeline_empty_results_raises(
        self,
        pipeline_service_with_crawler: PipelineServiceImpl,
        mock_pipeline: MagicMock,
        mock_crawler: MagicMock,
    ) -> None:
        """No crawl results must raise instead of silently succeeding."""
        mock_crawler.crawl_batch = AsyncMock(return_value=[])

        with pytest.raises(RuntimeError, match="no results"):
            await pipeline_service_with_crawler.run_full_pipeline("https://example.com/test")
        mock_pipeline.process_batch.assert_not_awaited()

    async def test_run_phase3_without_force_reprocess(
        self,
        pipeline_service: PipelineServiceImpl,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test run_phase3_per_article with default force_reprocess=False."""
        article_id = str(uuid.uuid4())

        await pipeline_service.run_phase3_per_article(article_id)

        mock_pipeline.process_article_phase3.assert_called_once_with(
            article_id=article_id,
            force_reprocess=False,
        )

    async def test_run_full_pipeline_without_source_name(
        self,
        pipeline_service_with_crawler: PipelineServiceImpl,
        mock_crawler: MagicMock,
    ) -> None:
        """Test run_full_pipeline without source_name uses default source."""
        url = "https://example.com/test"

        await pipeline_service_with_crawler.run_full_pipeline(url)

        item = mock_crawler.crawl_batch.await_args.args[0][0]
        assert item.source == "url_endpoint"

    async def test_service_handles_pipeline_errors(
        self,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test that service propagates pipeline errors."""
        mock_pipeline.process_article_phase3 = AsyncMock(
            side_effect=RuntimeError("Processing failed")
        )

        service = PipelineServiceImpl(mock_pipeline)

        with pytest.raises(RuntimeError, match="Processing failed"):
            await service.run_phase3_per_article("test-id")
