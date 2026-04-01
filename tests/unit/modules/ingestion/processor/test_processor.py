# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for DiscoveryProcessor (ingestion module)."""

from __future__ import annotations

import uuid
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


@pytest.fixture
def mock_deduplicator():
    """Mock deduplicator."""
    dedup = AsyncMock()
    dedup.dedup = AsyncMock(return_value=[])
    return dedup


@pytest.fixture
def mock_simhash_dedup():
    """Mock SimHash deduplicator."""
    simhash = AsyncMock()
    simhash.dedup_titles_with_metrics = AsyncMock(return_value=([], 0))
    return simhash


class TestDiscoveryProcessorInit:
    """Tests for DiscoveryProcessor initialization."""

    def test_processor_initializes(self, mock_crawler, mock_article_repo):
        """Test that processor initializes correctly."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        assert processor is not None
        assert processor._crawler == mock_crawler
        assert processor._article_repo == mock_article_repo

    def test_processor_with_pipeline(self, mock_crawler, mock_article_repo, mock_pipeline):
        """Test processor with optional pipeline."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            pipeline=mock_pipeline,
        )

        assert processor._pipeline is not None

    def test_processor_with_deduplicator(self, mock_crawler, mock_article_repo, mock_deduplicator):
        """Test processor with deduplicator."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
        )

        assert processor._deduplicator is not None

    def test_processor_with_simhash(self, mock_crawler, mock_article_repo, mock_simhash_dedup):
        """Test processor with SimHash deduplicator."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            simhash_dedup=mock_simhash_dedup,
        )

        assert processor._simhash_dedup is not None

    def test_processor_enable_simhash_flag(self, mock_crawler, mock_article_repo):
        """Test processor enable_simhash flag."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        assert processor._enable_simhash is False


class TestDiscoveryProcessorSetters:
    """Tests for DiscoveryProcessor setter methods."""

    def test_set_deduplicator(self, mock_crawler, mock_article_repo, mock_deduplicator):
        """Test setting deduplicator on processor."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        processor.set_deduplicator(mock_deduplicator)

        assert processor._deduplicator is mock_deduplicator

    def test_set_simhash_dedup(self, mock_crawler, mock_article_repo, mock_simhash_dedup):
        """Test setting SimHash deduplicator on processor."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        processor.set_simhash_dedup(mock_simhash_dedup)

        assert processor._simhash_dedup is mock_simhash_dedup

    def test_set_enable_simhash(self, mock_crawler, mock_article_repo):
        """Test enabling/disabling SimHash."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=True,
        )

        processor.set_enable_simhash(False)

        assert processor._enable_simhash is False

    def test_set_pipeline(self, mock_crawler, mock_article_repo, mock_pipeline):
        """Test setting pipeline on processor."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        processor.set_pipeline(mock_pipeline)

        assert processor._pipeline is mock_pipeline


class TestDiscoveryProcessorOnItemsDiscovered:
    """Tests for DiscoveryProcessor.on_items_discovered method."""

    @pytest.fixture
    def processor(self, mock_crawler, mock_article_repo):
        """Create DiscoveryProcessor instance."""
        from modules.ingestion.processor import DiscoveryProcessor

        return DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

    @pytest.fixture
    def mock_source(self):
        """Create mock source."""
        source = MagicMock()
        source.id = "test-source-id"
        source.name = "test_source"
        return source

    @pytest.fixture
    def mock_items(self):
        """Create mock news items."""
        item = MagicMock()
        item.url = "https://example.com/article1"
        item.title = "Test Article"
        item.name = "Test Article"
        return [item]

    @pytest.mark.asyncio
    async def test_on_items_discovered_empty_items(self, processor, mock_source):
        """Test on_items_discovered with empty items list."""
        await processor.on_items_discovered([], mock_source)

        # The processor does call crawl_batch with empty list
        # but no articles are inserted
        processor._article_repo.insert_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_deduplicator(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered with URL deduplication."""
        from modules.ingestion.processor import DiscoveryProcessor

        mock_dedup = AsyncMock()
        mock_dedup.dedup = AsyncMock(return_value=mock_items)

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_dedup,
        )

        mock_article = ArticleRaw(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.insert_raw = AsyncMock(return_value=uuid.uuid4())

        await processor.on_items_discovered(mock_items, mock_source)

        mock_dedup.dedup.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_all_deduplicated_by_url(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered when all items are filtered by URL dedup."""
        from modules.ingestion.processor import DiscoveryProcessor

        mock_dedup = AsyncMock()
        mock_dedup.dedup = AsyncMock(return_value=[])  # All filtered

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_dedup,
        )

        await processor.on_items_discovered(mock_items, mock_source)

        # Should not call crawler when all items are deduplicated
        mock_crawler.crawl_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_max_items(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """Test on_items_discovered with max_items limit."""
        from modules.ingestion.processor import DiscoveryProcessor

        items = [
            MagicMock(
                url=f"https://example.com/article{i}", title=f"Article {i}", name=f"Article {i}"
            )
            for i in range(10)
        ]

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        mock_article = ArticleRaw(
            url="https://example.com/article",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article] * 5)
        mock_article_repo.insert_raw = AsyncMock(return_value=uuid.uuid4())

        await processor.on_items_discovered(items, mock_source, max_items=5)

        # Should only pass 5 items to crawler
        call_args = mock_crawler.crawl_batch.call_args[0][0]
        assert len(call_args) == 5

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_task_id(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered with task_id."""
        from modules.ingestion.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        task_id = uuid.uuid4()
        mock_article = ArticleRaw(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.insert_raw = AsyncMock(return_value=uuid.uuid4())

        await processor.on_items_discovered(mock_items, mock_source, task_id=task_id)

        # Check task_id was passed to insert_raw
        mock_article_repo.insert_raw.assert_called_once()
        call_kwargs = mock_article_repo.insert_raw.call_args[1]
        assert call_kwargs.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_simhash(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """Test on_items_discovered with SimHash deduplication."""
        from modules.ingestion.processor import DiscoveryProcessor

        item = MagicMock()
        item.url = "https://example.com/article1"
        item.title = "Test Article"
        item.name = "Test Article"

        mock_simhash = AsyncMock()
        # Return one unique item
        from modules.ingestion.deduplication.simhash_dedup import TitleItem

        unique_item = TitleItem(url="https://example.com/article1", title="Test Article")
        mock_simhash.dedup_titles_with_metrics = AsyncMock(return_value=([unique_item], 0))

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            simhash_dedup=mock_simhash,
            enable_simhash=True,
        )

        mock_article = ArticleRaw(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.insert_raw = AsyncMock(return_value=uuid.uuid4())

        await processor.on_items_discovered([item], mock_source)

        mock_simhash.dedup_titles_with_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_simhash_disabled(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered with SimHash disabled."""
        from modules.ingestion.processor import DiscoveryProcessor

        mock_simhash = AsyncMock()

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            simhash_dedup=mock_simhash,
            enable_simhash=False,  # Disabled
        )

        mock_article = ArticleRaw(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.insert_raw = AsyncMock(return_value=uuid.uuid4())

        await processor.on_items_discovered(mock_items, mock_source)

        # Should not call simhash when disabled
        mock_simhash.dedup_titles_with_metrics.assert_not_called()


class TestDiscoveryProcessorErrorHandling:
    """Error handling tests for DiscoveryProcessor."""

    @pytest.fixture
    def processor(self, mock_crawler, mock_article_repo):
        """Create DiscoveryProcessor instance."""
        from modules.ingestion.processor import DiscoveryProcessor

        return DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

    @pytest.fixture
    def mock_source(self):
        """Create mock source."""
        source = MagicMock()
        source.id = "test-source-id"
        source.name = "test_source"
        return source

    @pytest.fixture
    def mock_items(self):
        """Create mock news items."""
        item = MagicMock()
        item.url = "https://example.com/article1"
        item.title = "Test Article"
        item.name = "Test Article"
        return [item]

    @pytest.mark.asyncio
    async def test_handles_crawler_error(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test processor handles crawler errors."""
        from modules.ingestion.processor import DiscoveryProcessor

        mock_crawler.crawl_batch = AsyncMock(side_effect=Exception("Crawler error"))

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        with pytest.raises(Exception, match="Crawler error"):
            await processor.on_items_discovered(mock_items, mock_source)

    @pytest.mark.asyncio
    async def test_handles_repo_insert_error(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test processor handles repository insert errors gracefully."""
        from modules.ingestion.processor import DiscoveryProcessor

        mock_article = ArticleRaw(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.insert_raw = AsyncMock(side_effect=Exception("DB error"))

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        # Should not raise, logs error and continues
        await processor.on_items_discovered(mock_items, mock_source)

    @pytest.mark.asyncio
    async def test_handles_pipeline_error(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test processor handles pipeline errors gracefully."""
        from modules.ingestion.processor import DiscoveryProcessor

        mock_pipeline = AsyncMock()
        mock_pipeline.process_batch = AsyncMock(side_effect=Exception("Pipeline error"))

        mock_article = ArticleRaw(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.insert_raw = AsyncMock(return_value=uuid.uuid4())

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            pipeline=mock_pipeline,
        )

        # Should not raise, logs error
        await processor.on_items_discovered(mock_items, mock_source)

    @pytest.mark.asyncio
    async def test_handles_fetch_error_in_batch(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test processor handles FetchError in batch results."""
        from modules.ingestion.fetching.exceptions import FetchError
        from modules.ingestion.processor import DiscoveryProcessor

        fetch_error = FetchError(
            url="https://example.com/failed",
            message="Failed to fetch",
            cause=None,
        )
        mock_article = ArticleRaw(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        mock_crawler.crawl_batch = AsyncMock(return_value=[fetch_error, mock_article])
        mock_article_repo.insert_raw = AsyncMock(return_value=uuid.uuid4())

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        await processor.on_items_discovered(mock_items, mock_source)

        # Should only insert the successful article
        mock_article_repo.insert_raw.assert_called_once()
