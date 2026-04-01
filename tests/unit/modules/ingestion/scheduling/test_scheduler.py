# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SourceScheduler."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSourceSchedulerInit:
    """Tests for SourceScheduler initialization."""

    def test_init_with_params(self):
        """Test SourceScheduler initializes with params."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        mock_callback = AsyncMock()

        scheduler = SourceScheduler(
            registry=mock_registry,
            on_items_discovered=mock_callback,
        )

        assert scheduler._registry is mock_registry
        assert scheduler._on_items is mock_callback


class TestSourceSchedulerStartStop:
    """Tests for SourceScheduler start/stop."""

    @pytest.fixture
    def scheduler(self):
        """Create SourceScheduler instance."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        mock_registry.list_sources.return_value = []

        return SourceScheduler(
            registry=mock_registry,
            on_items_discovered=AsyncMock(),
        )

    def test_start_schedules_sources(self, scheduler):
        """Test start() schedules all enabled sources."""
        mock_source = MagicMock()
        mock_source.id = "source-1"
        mock_source.interval_minutes = 30

        scheduler._registry.list_sources.return_value = [mock_source]

        with patch.object(scheduler._scheduler, "start") as mock_start:
            with patch.object(scheduler._scheduler, "add_job") as mock_add_job:
                scheduler.start()

                mock_start.assert_called_once()
                mock_add_job.assert_called_once()

    def test_stop_shuts_down_scheduler(self, scheduler):
        """Test stop() shuts down scheduler."""
        with patch.object(scheduler._scheduler, "shutdown") as mock_shutdown:
            scheduler.stop()

            mock_shutdown.assert_called_once_with(wait=False)


class TestSourceSchedulerCrawlSource:
    """Tests for _crawl_source()."""

    @pytest.fixture
    def scheduler(self):
        """Create SourceScheduler instance."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        return SourceScheduler(
            registry=mock_registry,
            on_items_discovered=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_crawl_source_disabled_source(self, scheduler):
        """Test _crawl_source skips disabled sources."""
        mock_source = MagicMock()
        mock_source.enabled = False

        scheduler._registry.get_source.return_value = mock_source

        await scheduler._crawl_source("source-1")

        scheduler._registry.get_parser.assert_not_called()

    @pytest.mark.asyncio
    async def test_crawl_source_no_parser(self, scheduler):
        """Test _crawl_source handles missing parser."""
        mock_source = MagicMock()
        mock_source.enabled = True
        mock_source.source_type = "rss"

        scheduler._registry.get_source.return_value = mock_source
        scheduler._registry.get_parser.return_value = None

        await scheduler._crawl_source("source-1")

        scheduler._registry.get_parser.assert_called_once_with("rss")

    @pytest.mark.asyncio
    async def test_crawl_source_parses_and_calls_callback(self, scheduler):
        """Test _crawl_source parses and calls callback."""
        from modules.ingestion.domain.models import NewsItem

        mock_source = MagicMock()
        mock_source.enabled = True
        mock_source.source_type = "rss"
        mock_source.id = "source-1"

        mock_parser = MagicMock()
        mock_item = MagicMock(spec=NewsItem)
        mock_parser.parse = AsyncMock(return_value=[mock_item])

        scheduler._registry.get_source.return_value = mock_source
        scheduler._registry.get_parser.return_value = mock_parser

        await scheduler._crawl_source("source-1", max_items=10)

        mock_parser.parse.assert_called_once_with(mock_source)
        scheduler._on_items.assert_called_once()

    @pytest.mark.asyncio
    async def test_crawl_source_handles_exception(self, scheduler):
        """Test _crawl_source handles exceptions."""
        mock_source = MagicMock()
        mock_source.enabled = True
        mock_source.source_type = "rss"

        mock_parser = MagicMock()
        mock_parser.parse = AsyncMock(side_effect=Exception("Parse error"))

        scheduler._registry.get_source.return_value = mock_source
        scheduler._registry.get_parser.return_value = mock_parser

        # Should not raise
        await scheduler._crawl_source("source-1")


class TestSourceSchedulerTriggerNow:
    """Tests for trigger_now()."""

    @pytest.fixture
    def scheduler(self):
        """Create SourceScheduler instance."""
        from modules.ingestion.scheduling.scheduler import SourceScheduler

        mock_registry = MagicMock()
        return SourceScheduler(
            registry=mock_registry,
            on_items_discovered=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_trigger_now_calls_crawl_source(self, scheduler):
        """Test trigger_now() calls _crawl_source."""
        scheduler._crawl_source = AsyncMock()

        await scheduler.trigger_now("source-1", max_items=5, task_id=None)

        scheduler._crawl_source.assert_called_once_with("source-1", 5, None)
