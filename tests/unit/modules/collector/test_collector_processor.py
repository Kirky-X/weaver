# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for DiscoveryProcessor."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import RawArticle
from modules.ingestion.fetching.exceptions import FetchError


@pytest.fixture
def sample_article():
    """Create sample article for testing."""
    return RawArticle(
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
def mock_processing_queue():
    """Mock processing queue."""
    return AsyncMock()


@pytest.fixture
def mock_deduplicator():
    """Mock deduplicator."""
    return AsyncMock()


@pytest.fixture
def mock_simhash_dedup():
    """Mock SimHash deduplicator."""
    return AsyncMock()


@pytest.fixture
def sample_items():
    """Create sample news items for testing."""
    item1 = MagicMock()
    item1.url = "https://example.com/article1"
    item1.title = "Test Article 1"
    item1.name = "Test Article 1"
    item2 = MagicMock()
    item2.url = "https://example.com/article2"
    item2.title = "Test Article 2"
    item2.name = "Test Article 2"
    return [item1, item2]


@pytest.fixture
def mock_source():
    """Create mock source configuration."""
    source = MagicMock()
    source.id = "test_source"
    return source


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
    async def test_processor_with_processing_queue(
        self, mock_crawler, mock_article_repo, mock_processing_queue
    ):
        """Test processor with optional processing queue."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            processing_queue=mock_processing_queue,
        )

        assert processor._processing_queue is not None

    @pytest.mark.asyncio
    async def test_processor_with_simhash_enabled(self, mock_crawler, mock_article_repo):
        """Test processor with SimHash enabled."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=True,
        )

        assert processor._enable_simhash is True

    @pytest.mark.asyncio
    async def test_processor_with_simhash_disabled(self, mock_crawler, mock_article_repo):
        """Test processor with SimHash disabled."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        assert processor._enable_simhash is False


class TestDiscoveryProcessorSetterMethods:
    """Tests for DiscoveryProcessor setter methods."""

    @pytest.mark.asyncio
    async def test_set_deduplicator(self, mock_crawler, mock_article_repo):
        """Test setting deduplicator on processor."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        mock_deduplicator = MagicMock()
        processor.set_deduplicator(mock_deduplicator)

        assert processor._deduplicator is not None

    @pytest.mark.asyncio
    async def test_set_simhash_dedup(self, mock_crawler, mock_article_repo):
        """Test setting SimHash deduplicator on processor."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        mock_simhash = MagicMock()
        processor.set_simhash_dedup(mock_simhash)

        assert processor._simhash_dedup is not None

    @pytest.mark.asyncio
    async def test_set_enable_simhash(self, mock_crawler, mock_article_repo):
        """Test enabling/disabling SimHash."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        processor.set_enable_simhash(True)

        assert processor._enable_simhash is True


class TestDiscoveryProcessorOnItemsDiscovered:
    """Tests for on_items_discovered method."""

    @pytest.mark.asyncio
    async def test_on_items_discovered_basic_flow(
        self,
        mock_crawler,
        mock_article_repo,
        mock_processing_queue,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test basic flow without deduplication."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        # Setup mocks
        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])
        mock_processing_queue.enqueue = AsyncMock(return_value=True)

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            processing_queue=mock_processing_queue,
            deduplicator=None,  # No deduplication
            simhash_dedup=None,
            enable_simhash=False,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        mock_crawler.crawl_batch.assert_called_once()
        mock_article_repo.bulk_insert_raw.assert_called_once()
        mock_processing_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_url_dedup(
        self,
        mock_crawler,
        mock_article_repo,
        mock_deduplicator,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test flow with URL deduplication."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        # Deduplicator returns only one item
        mock_deduplicator.dedup = AsyncMock(return_value=[sample_items[0]])
        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
            enable_simhash=False,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        mock_deduplicator.dedup.assert_called_once()
        mock_crawler.crawl_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_all_deduplicated_by_url(
        self,
        mock_crawler,
        mock_article_repo,
        mock_deduplicator,
        sample_items,
        mock_source,
    ):
        """Test when all items are filtered by URL deduplication."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        # All items filtered
        mock_deduplicator.dedup = AsyncMock(return_value=[])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        mock_crawler.crawl_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_simhash_dedup(
        self,
        mock_crawler,
        mock_article_repo,
        mock_deduplicator,
        mock_simhash_dedup,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test flow with SimHash deduplication."""
        from modules.ingestion.deduplication import TitleItem
        from modules.ingestion.domain.processor import DiscoveryProcessor

        # URL dedup returns all items
        mock_deduplicator.dedup = AsyncMock(return_value=sample_items)
        # SimHash returns unique items
        unique_items = [TitleItem(url=sample_items[0].url, title=sample_items[0].title)]
        mock_simhash_dedup.dedup_titles_with_metrics = AsyncMock(return_value=(unique_items, 1))
        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
            simhash_dedup=mock_simhash_dedup,
            enable_simhash=True,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        mock_simhash_dedup.dedup_titles_with_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_simhash_disabled(
        self,
        mock_crawler,
        mock_article_repo,
        mock_deduplicator,
        mock_simhash_dedup,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test that SimHash is skipped when disabled."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_deduplicator.dedup = AsyncMock(return_value=sample_items)
        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
            simhash_dedup=mock_simhash_dedup,
            enable_simhash=False,  # Disabled
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        # SimHash should not be called
        mock_simhash_dedup.dedup_titles_with_metrics.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_max_items_limit(
        self,
        mock_crawler,
        mock_article_repo,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test max_items limit."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        # 5 items, max_items=2
        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
            max_items=1,
        )

        # Should only process 1 item
        call_args = mock_crawler.crawl_batch.call_args
        assert len(call_args[0][0]) == 1

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_fetch_errors(
        self,
        mock_crawler,
        mock_article_repo,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test handling of fetch errors."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        fetch_error = FetchError(
            url="https://example.com/failed",
            message="Connection timeout",
            cause=None,
        )

        # Mix of success and failure
        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article, fetch_error])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        # Should only insert successful article
        mock_article_repo.bulk_insert_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_no_successful_articles(
        self,
        mock_crawler,
        mock_article_repo,
        sample_items,
        mock_source,
    ):
        """Test when all fetch attempts fail."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        fetch_error = FetchError(
            url="https://example.com/failed",
            message="Connection timeout",
            cause=None,
        )

        mock_crawler.crawl_batch = AsyncMock(return_value=[fetch_error])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        mock_article_repo.bulk_insert_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_items_discovered_insert_error(
        self,
        mock_crawler,
        mock_article_repo,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test handling of insert errors."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(side_effect=Exception("DB error"))

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        # Should not raise, just log
        mock_article_repo.bulk_insert_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_task_id(
        self,
        mock_crawler,
        mock_article_repo,
        mock_processing_queue,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test with task_id parameter."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        task_id = uuid.uuid4()
        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])
        mock_processing_queue.enqueue = AsyncMock(return_value=True)

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            processing_queue=mock_processing_queue,
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
            task_id=task_id,
        )

        # Check task_id was passed to bulk_insert_raw
        call_args = mock_article_repo.bulk_insert_raw.call_args
        assert call_args[1]["task_id"] == task_id

        # Check task_id was passed to enqueue
        enqueue_args = mock_processing_queue.enqueue.call_args
        assert enqueue_args[1]["task_id"] == str(task_id)

    @pytest.mark.asyncio
    async def test_on_items_discovered_queue_full(
        self,
        mock_crawler,
        mock_article_repo,
        mock_processing_queue,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test handling when queue is full (soft backpressure)."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])
        mock_processing_queue.enqueue = AsyncMock(return_value=False)  # Queue full

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            processing_queue=mock_processing_queue,
        )

        # Should not raise, just skip remaining articles
        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        # Insert should have been called before queue full
        mock_article_repo.bulk_insert_raw.assert_called_once()
        # Enqueue should have been attempted
        mock_processing_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_no_processing_queue(
        self,
        mock_crawler,
        mock_article_repo,
        sample_items,
        mock_source,
        sample_article,
    ):
        """Test without processing queue (processing_queue=None)."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            processing_queue=None,  # No queue
        )

        await processor.on_items_discovered(
            items=sample_items,
            source=mock_source,
        )

        mock_article_repo.bulk_insert_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_items_without_title(
        self,
        mock_crawler,
        mock_article_repo,
        mock_simhash_dedup,
        mock_source,
        sample_article,
    ):
        """Test items without title are handled in SimHash dedup."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        # Item without title
        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = None
        item.name = ""

        mock_deduplicator = AsyncMock()
        mock_deduplicator.dedup = AsyncMock(return_value=[item])
        mock_crawler.crawl_batch = AsyncMock(return_value=[sample_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
            simhash_dedup=mock_simhash_dedup,
            enable_simhash=True,
        )

        await processor.on_items_discovered(
            items=[item],
            source=mock_source,
        )

        # SimHash should not be called since no title items
        mock_simhash_dedup.dedup_titles_with_metrics.assert_not_called()


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
    async def test_on_items_discovered_empty_items(
        self,
        mock_crawler,
        mock_article_repo,
        mock_source,
    ):
        """Test with empty items list - crawl_batch is called with empty list."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        # Return empty list for empty batch
        mock_crawler.crawl_batch = AsyncMock(return_value=[])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        await processor.on_items_discovered(
            items=[],
            source=mock_source,
        )

        # crawl_batch is called with empty list, but no articles to insert
        mock_crawler.crawl_batch.assert_called_once_with([])
        mock_article_repo.bulk_insert_raw.assert_not_called()


class TestDiscoveryProcessorErrorHandling:
    """Error handling tests for DiscoveryProcessor."""

    @pytest.mark.asyncio
    async def test_on_items_discovered_crawler_exception(
        self,
        mock_crawler,
        mock_article_repo,
        sample_items,
        mock_source,
    ):
        """Test processor handles crawler exceptions."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_crawler.crawl_batch = AsyncMock(side_effect=Exception("Crawler error"))

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        with pytest.raises(Exception, match="Crawler error"):
            await processor.on_items_discovered(
                items=sample_items,
                source=mock_source,
            )

    @pytest.mark.asyncio
    async def test_on_items_discovered_deduplicator_exception(
        self,
        mock_crawler,
        mock_article_repo,
        mock_deduplicator,
        sample_items,
        mock_source,
    ):
        """Test processor handles deduplicator exceptions."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_deduplicator.dedup = AsyncMock(side_effect=Exception("Dedup error"))

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
        )

        with pytest.raises(Exception, match="Dedup error"):
            await processor.on_items_discovered(
                items=sample_items,
                source=mock_source,
            )
