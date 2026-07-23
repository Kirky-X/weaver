# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for DiscoveryProcessor (ingestion module)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle


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
    repo = AsyncMock()
    # DB title dedup returns empty set by default (no existing titles)
    repo.get_existing_titles = AsyncMock(return_value=set())
    return repo


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
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        assert processor is not None
        assert processor._crawler == mock_crawler
        assert processor._article_repo == mock_article_repo

    def test_processor_with_pipeline(self, mock_crawler, mock_article_repo, mock_pipeline):
        """Test processor with optional processing queue."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            processing_queue=mock_pipeline,
        )

        assert processor._processing_queue is not None

    def test_processor_with_deduplicator(self, mock_crawler, mock_article_repo, mock_deduplicator):
        """Test processor with deduplicator."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_deduplicator,
        )

        assert processor._deduplicator is not None

    def test_processor_with_simhash(self, mock_crawler, mock_article_repo, mock_simhash_dedup):
        """Test processor with SimHash deduplicator."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            simhash_dedup=mock_simhash_dedup,
        )

        assert processor._simhash_dedup is not None

    def test_processor_enable_simhash_flag(self, mock_crawler, mock_article_repo):
        """Test processor enable_simhash flag."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

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
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        processor.set_deduplicator(mock_deduplicator)

        assert processor._deduplicator is mock_deduplicator

    def test_set_simhash_dedup(self, mock_crawler, mock_article_repo, mock_simhash_dedup):
        """Test setting SimHash deduplicator on processor."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        processor.set_simhash_dedup(mock_simhash_dedup)

        assert processor._simhash_dedup is mock_simhash_dedup

    def test_set_enable_simhash(self, mock_crawler, mock_article_repo):
        """Test enabling/disabling SimHash."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=True,
        )

        processor.set_enable_simhash(False)

        assert processor._enable_simhash is False


class TestDiscoveryProcessorOnItemsDiscovered:
    """Tests for DiscoveryProcessor.on_items_discovered method."""

    @pytest.fixture
    def processor(self, mock_crawler, mock_article_repo):
        """Create DiscoveryProcessor instance."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

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
        processor._article_repo.bulk_insert_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_deduplicator(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered with URL deduplication."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_dedup = AsyncMock()
        mock_dedup.dedup = AsyncMock(return_value=mock_items)

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            deduplicator=mock_dedup,
        )

        mock_article = RawArticle(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        await processor.on_items_discovered(mock_items, mock_source)

        mock_dedup.dedup.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_all_deduplicated_by_url(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered when all items are filtered by URL dedup."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

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
        from modules.ingestion.domain.processor import DiscoveryProcessor

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

        mock_article = RawArticle(
            url="https://example.com/article",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article] * 5)
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        await processor.on_items_discovered(items, mock_source, max_items=5)

        # Should only pass 5 items to crawler
        call_args = mock_crawler.crawl_batch.call_args[0][0]
        assert len(call_args) == 5

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_task_id(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered with task_id."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        task_id = uuid.uuid4()
        mock_article = RawArticle(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        await processor.on_items_discovered(mock_items, mock_source, task_id=task_id)

        # Check task_id was passed to bulk_insert_raw
        mock_article_repo.bulk_insert_raw.assert_called_once()
        call_kwargs = mock_article_repo.bulk_insert_raw.call_args[1]
        assert call_kwargs.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_on_items_discovered_with_simhash(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """Test on_items_discovered with SimHash deduplication."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

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

        mock_article = RawArticle(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        await processor.on_items_discovered([item], mock_source)

        mock_simhash.dedup_titles_with_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_items_discovered_simhash_disabled(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test on_items_discovered with SimHash disabled."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_simhash = AsyncMock()

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            simhash_dedup=mock_simhash,
            enable_simhash=False,  # Disabled
        )

        mock_article = RawArticle(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        await processor.on_items_discovered(mock_items, mock_source)

        # Should not call simhash when disabled
        mock_simhash.dedup_titles_with_metrics.assert_not_called()


class TestDiscoveryProcessorDbTitleDedup:
    """Tests for DB-level title deduplication (Stage 3 safety net).

    When SimHash fingerprints are missing (Redis degradation, process
    restart, scheduler timing), the DB title check prevents duplicate
    articles from being inserted.
    """

    @pytest.fixture
    def mock_source(self):
        source = MagicMock()
        source.id = "test-source-id"
        source.name = "test_source"
        return source

    @pytest.mark.asyncio
    async def test_db_title_dedup_filters_existing_title(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """Items with titles already in DB should be filtered before crawl."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        item = MagicMock()
        item.url = "https://example.com/new-url"
        item.title = "10间敢死队"
        item.name = "10间敢死队"

        # DB already has this title
        mock_article_repo.get_existing_titles = AsyncMock(return_value={"10间敢死队"})
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        await processor.on_items_discovered([item], mock_source)

        # Should NOT crawl items whose titles already exist in DB
        mock_crawler.crawl_batch.assert_not_called()
        mock_article_repo.bulk_insert_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_title_dedup_passes_new_title(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """Items with new titles should pass through to crawl."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        item = MagicMock()
        item.url = "https://example.com/new-article"
        item.title = "Brand New Story"
        item.name = "Brand New Story"

        mock_article_repo.get_existing_titles = AsyncMock(return_value=set())
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        mock_article = RawArticle(
            url="https://example.com/new-article",
            title="Brand New Story",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        await processor.on_items_discovered([item], mock_source)

        mock_crawler.crawl_batch.assert_called_once()
        mock_article_repo.bulk_insert_raw.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_title_dedup_partial_filter(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """Mixed batch: some titles exist, some don't — only new ones crawl."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        item_old = MagicMock()
        item_old.url = "https://example.com/old"
        item_old.title = "Existing Title"
        item_old.name = "Existing Title"

        item_new = MagicMock()
        item_new.url = "https://example.com/new"
        item_new.title = "New Title"
        item_new.name = "New Title"

        mock_article_repo.get_existing_titles = AsyncMock(return_value={"Existing Title"})
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        mock_article = RawArticle(
            url="https://example.com/new",
            title="New Title",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        await processor.on_items_discovered([item_old, item_new], mock_source)

        # Only new item should be crawled
        crawled_items = mock_crawler.crawl_batch.call_args[0][0]
        assert len(crawled_items) == 1
        assert crawled_items[0].url == "https://example.com/new"

    @pytest.mark.asyncio
    async def test_db_title_dedup_skipped_in_force_mode(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """force=True should bypass DB title dedup (user wants re-crawl)."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        item = MagicMock()
        item.url = "https://example.com/existing"
        item.title = "Existing Title"
        item.name = "Existing Title"

        mock_article_repo.get_existing_titles = AsyncMock(return_value={"Existing Title"})
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        mock_article = RawArticle(
            url="https://example.com/existing",
            title="Existing Title",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        # force=True: should NOT call get_existing_titles
        await processor.on_items_discovered([item], mock_source, force=True)

        mock_article_repo.get_existing_titles.assert_not_called()
        mock_crawler.crawl_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_title_dedup_skipped_when_method_missing(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """When repo lacks get_existing_titles, Stage 3 is skipped (backward compat)."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Some Title"
        item.name = "Some Title"

        # Remove get_existing_titles to simulate legacy repo
        del mock_article_repo.get_existing_titles
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        mock_article = RawArticle(
            url="https://example.com/article",
            title="Some Title",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        # Should proceed to crawl without error
        await processor.on_items_discovered([item], mock_source)

        mock_crawler.crawl_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_title_dedup_degrades_on_db_failure(
        self, mock_crawler, mock_article_repo, mock_source
    ):
        """DB failure in safety net should degrade gracefully (process all items)."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        item = MagicMock()
        item.url = "https://example.com/article"
        item.title = "Some Title"
        item.name = "Some Title"

        mock_article_repo.get_existing_titles = AsyncMock(
            side_effect=RuntimeError("DB connection lost")
        )
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        mock_article = RawArticle(
            url="https://example.com/article",
            title="Some Title",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            enable_simhash=False,
        )

        # DB failure should NOT abort the batch — degrade to crawl all items
        await processor.on_items_discovered([item], mock_source)

        mock_crawler.crawl_batch.assert_called_once()
        mock_article_repo.bulk_insert_raw.assert_called_once()


class TestDiscoveryProcessorErrorHandling:
    """Error handling tests for DiscoveryProcessor."""

    @pytest.fixture
    def processor(self, mock_crawler, mock_article_repo):
        """Create DiscoveryProcessor instance."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

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
        from modules.ingestion.domain.processor import DiscoveryProcessor

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
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_article = RawArticle(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(side_effect=Exception("DB error"))

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
        """Test processor handles processing queue operations gracefully."""
        from modules.ingestion.domain.processor import DiscoveryProcessor

        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock(return_value=True)

        mock_article = RawArticle(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )
        mock_crawler.crawl_batch = AsyncMock(return_value=[mock_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
            processing_queue=mock_queue,
        )

        # Should not raise
        await processor.on_items_discovered(mock_items, mock_source)

    @pytest.mark.asyncio
    async def test_handles_fetch_error_in_batch(
        self, mock_crawler, mock_article_repo, mock_source, mock_items
    ):
        """Test processor handles FetchError in batch results."""
        from modules.ingestion.domain.processor import DiscoveryProcessor
        from modules.ingestion.fetching.exceptions import FetchError

        fetch_error = FetchError(
            url="https://example.com/failed",
            message="Failed to fetch",
            cause=None,
        )
        mock_article = RawArticle(
            url="https://example.com/article1",
            title="Test Article",
            body="Content",
            source="test_source",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        mock_crawler.crawl_batch = AsyncMock(return_value=[fetch_error, mock_article])
        mock_article_repo.bulk_insert_raw = AsyncMock(return_value=[uuid.uuid4()])

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_article_repo,
        )

        await processor.on_items_discovered(mock_items, mock_source)

        # Should only insert the successful article
        mock_article_repo.bulk_insert_raw.assert_called_once()
