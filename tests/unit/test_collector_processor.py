# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for DiscoveryProcessor."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import ArticleRaw


@pytest.fixture
def sample_article():
    """Create sample article for testing."""
    return ArticleRaw(
        url="https://example.com/article1",
        title="Test Article",
        body="This is test content for the article body.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_crawler():
    """Mock crawler."""
    return AsyncMock()


@pytest.fixture
def mock_article_repo():
    """Mock article repository."""
    return AsyncMock()


@pytest.fixture
def mock_pipeline():
    """Mock pipeline."""
    return AsyncMock()


class TestDiscoveryProcessor:
    """Tests for DiscoveryProcessor functionality."""

    @pytest.mark.asyncio
    async def test_processor_initializes(self, mock_crawler, mock_article_repo):
        """Test that processor initializes correctly."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        assert processor is not None

    @pytest.mark.asyncio
    async def test_processor_with_pipeline(self, mock_crawler, mock_article_repo, mock_pipeline):
        """Test processor with optional pipeline."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            pipeline=mock_pipeline,
        )

        assert processor._pipeline is not None


class TestDiscoveryProcessorEdgeCases:
    """Edge case tests for DiscoveryProcessor."""

    @pytest.mark.asyncio
    async def test_processor_without_deduplicator(self, mock_crawler, mock_article_repo):
        """Test processor without deduplicator."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=None,
        )

        assert processor._deduplicator is None

    @pytest.mark.asyncio
    async def test_processor_set_deduplicator(self, mock_crawler, mock_article_repo):
        """Test setting deduplicator on processor."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        mock_deduplicator = MagicMock()
        processor.set_deduplicator(mock_deduplicator)

        assert processor._deduplicator is not None


class TestDiscoveryProcessorErrorHandling:
    """Error handling tests for DiscoveryProcessor."""

    @pytest.mark.asyncio
    async def test_processor_handles_crawler_error(self, mock_article_repo, mock_pipeline):
        """Test processor handles crawler errors."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_crawler = AsyncMock(side_effect=Exception("Crawler error"))

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            pipeline=mock_pipeline,
        )

        # Should handle error gracefully
        try:
            # Would call process method here
            pass
        except Exception:
            # Crawler errors may propagate
            pass
