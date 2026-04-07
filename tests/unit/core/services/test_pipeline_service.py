# Copyright (c) 2026 KirkyX. All Rights Reserved
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
    pipeline.run = AsyncMock(
        return_value={
            "article_id": "test-article-id",
            "url": "https://example.com/test",
            "status": "completed",
        }
    )
    return pipeline


@pytest.fixture
def pipeline_service(mock_pipeline: MagicMock) -> PipelineServiceImpl:
    """Create a PipelineServiceImpl instance."""
    return PipelineServiceImpl(mock_pipeline)


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

    async def test_run_full_pipeline_delegates_to_pipeline(
        self,
        pipeline_service: PipelineServiceImpl,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test that run_full_pipeline delegates to pipeline."""
        url = "https://example.com/test"

        result = await pipeline_service.run_full_pipeline(
            url=url,
            source_name="test-source",
        )

        # Verify delegation
        mock_pipeline.run.assert_called_once_with(
            url=url,
            source_name="test-source",
        )

        # Verify result
        assert result["article_id"] == "test-article-id"
        assert result["url"] == url

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
        pipeline_service: PipelineServiceImpl,
        mock_pipeline: MagicMock,
    ) -> None:
        """Test run_full_pipeline without source_name."""
        url = "https://example.com/test"

        await pipeline_service.run_full_pipeline(url)

        mock_pipeline.run.assert_called_once_with(
            url=url,
            source_name=None,
        )

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
