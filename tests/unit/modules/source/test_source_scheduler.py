# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SourceScheduler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_fetcher():
    """Mock fetcher."""
    return AsyncMock()


class TestSourceSchedulerBasic:
    """Basic functionality tests for SourceScheduler."""

    @pytest.mark.asyncio
    async def test_scheduler_initializes_with_registry(self, mock_fetcher):
        """Test that scheduler initializes with registry."""
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        async def on_items(items, config, task_id):
            pass

        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        assert scheduler is not None

    @pytest.mark.asyncio
    async def test_scheduler_start_stop(self, mock_fetcher):
        """Test that scheduler can start and stop."""
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        async def on_items(items, config, task_id):
            pass

        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        scheduler.start()
        scheduler.stop()

        # Should complete without error


class TestSourceSchedulerEdgeCases:
    """Edge case tests for SourceScheduler."""

    @pytest.mark.asyncio
    async def test_scheduler_with_disabled_sources(self, mock_fetcher):
        """Test scheduler behavior with disabled sources."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Add disabled source
        config = SourceConfig(
            id="disabled_source",
            name="Disabled Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=False,
        )
        registry.add_source(config)

        async def on_items(items, config, task_id):
            pass

        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        # Start should not fail with disabled sources
        scheduler.start()
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_scheduler_can_start_with_sources(self, mock_fetcher):
        """Test scheduler can start with registered sources."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Add enabled source
        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        async def on_items(items, config, task_id):
            pass

        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        scheduler.start()
        scheduler.stop()


class TestSourceSchedulerErrorHandling:
    """Error handling tests for SourceScheduler."""

    @pytest.mark.asyncio
    async def test_scheduler_handles_invalid_callback(self, mock_fetcher):
        """Test scheduler handles invalid callback gracefully."""
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Use non-async callback
        def invalid_callback(items, config, task_id):
            pass

        # Should handle gracefully
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=invalid_callback,
        )

        assert scheduler is not None


class TestSourceSchedulerCrawlSource:
    """Tests for _crawl_source method."""

    @pytest.mark.asyncio
    async def test_crawl_source_with_no_parser(self, mock_fetcher):
        """Test crawl_source when no parser is found."""
        from unittest.mock import MagicMock

        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Add source with unknown type
        config = SourceConfig(
            id="unknown_type_source",
            name="Unknown Type Source",
            url="https://example.com/feed",
            source_type="unknown_type",
            enabled=True,
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        await scheduler._crawl_source("unknown_type_source")

        # Should not call on_items since no parser
        on_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_crawl_source_with_disabled_source(self, mock_fetcher):
        """Test crawl_source when source is disabled."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Add disabled source
        config = SourceConfig(
            id="disabled_source",
            name="Disabled Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=False,
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        await scheduler._crawl_source("disabled_source")

        # Should not call on_items since source is disabled
        on_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_crawl_source_with_unknown_id(self, mock_fetcher):
        """Test crawl_source with non-existent source ID."""
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        await scheduler._crawl_source("nonexistent_source")

        # Should not call on_items since source doesn't exist
        on_items.assert_not_called()

    @pytest.mark.asyncio
    async def test_crawl_source_with_items(self, mock_fetcher):
        """Test crawl_source when parser returns items."""
        from datetime import UTC, datetime

        from modules.ingestion.parsing.models import NewsItem, SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.parsing.rss_parser import RSSParser
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        # Mock parser to return items
        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(
            return_value=[
                NewsItem(
                    url="https://example.com/article1",
                    title="Article 1",
                    body="Body 1",
                    source="test",
                    source_host="example.com",
                    pubDate=datetime.now(UTC),
                )
            ]
        )

        registry = SourceRegistry(fetcher=mock_fetcher)
        registry.register_parser("rss", mock_parser)

        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        await scheduler._crawl_source("test_source")

        # Should call on_items with found items
        on_items.assert_called_once()
        call_args = on_items.call_args
        items, source, max_items, task_id = call_args[0]
        assert len(items) == 1
        assert items[0].title == "Article 1"

    @pytest.mark.asyncio
    async def test_crawl_source_updates_last_crawl_time(self, mock_fetcher):
        """Test that crawl_source updates last_crawl_time when items found."""
        from datetime import UTC, datetime

        from modules.ingestion.parsing.models import NewsItem, SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(
            return_value=[
                NewsItem(
                    url="https://example.com/article1",
                    title="Article 1",
                    body="Body 1",
                    source="test",
                    source_host="example.com",
                    pubDate=datetime.now(UTC),
                )
            ]
        )

        registry = SourceRegistry(fetcher=mock_fetcher)
        registry.register_parser("rss", mock_parser)

        config = SourceConfig(
            id="test_source_time",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        # Initially no last_crawl_time
        assert config.last_crawl_time is None

        await scheduler._crawl_source("test_source_time")

        # Should be updated when items are found
        assert config.last_crawl_time is not None

    @pytest.mark.asyncio
    async def test_crawl_source_handles_parser_error(self, mock_fetcher):
        """Test crawl_source handles parser exceptions."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(side_effect=Exception("Parse error"))

        registry = SourceRegistry(fetcher=mock_fetcher)
        registry.register_parser("rss", mock_parser)

        config = SourceConfig(
            id="error_source",
            name="Error Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        # Should not raise
        await scheduler._crawl_source("error_source")

        # Should not call on_items
        on_items.assert_not_called()


class TestSourceSchedulerTriggerNow:
    """Tests for trigger_now method."""

    @pytest.mark.asyncio
    async def test_trigger_now_calls_crawl_source(self, mock_fetcher):
        """Test that trigger_now delegates to _crawl_source."""
        from unittest.mock import patch

        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        with patch.object(scheduler, "_crawl_source", new_callable=AsyncMock) as mock_crawl:
            await scheduler.trigger_now("test_source", max_items=10, task_id=None)

            mock_crawl.assert_called_once_with("test_source", 10, None)

    @pytest.mark.asyncio
    async def test_trigger_now_with_task_id(self, mock_fetcher):
        """Test trigger_now with task_id parameter."""
        import uuid

        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        on_items = AsyncMock()
        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        task_id = uuid.uuid4()
        # Should not raise
        await scheduler.trigger_now("test_source", task_id=task_id)
