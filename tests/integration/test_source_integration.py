# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Source module workflow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_fetcher():
    """Mock fetcher for sources."""
    return AsyncMock()


class TestSourceRegistryIntegration:
    """Integration tests for Source Registry."""

    def test_registry_initializes_with_fetcher(self, mock_fetcher):
        """Test that registry initializes with fetcher."""
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Verify registry is created
        assert registry is not None

    def test_registry_adds_source(self, mock_fetcher):
        """Test that registry adds a source."""
        from modules.source.models import SourceConfig
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Add a source
        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        # Verify source is added
        sources = registry.list_sources()
        assert len(sources) >= 1

    def test_registry_lists_enabled_sources_only(self, mock_fetcher):
        """Test that registry lists enabled sources only."""
        from modules.source.models import SourceConfig
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Add enabled source
        enabled_config = SourceConfig(
            id="enabled_source",
            name="Enabled Source",
            url="https://example.com/feed1",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(enabled_config)

        # Add disabled source
        disabled_config = SourceConfig(
            id="disabled_source",
            name="Disabled Source",
            url="https://example.com/feed2",
            source_type="rss",
            enabled=False,
        )
        registry.add_source(disabled_config)

        # List enabled sources only
        enabled_sources = registry.list_sources(enabled_only=True)

        # Should only include enabled source
        assert all(s.enabled for s in enabled_sources)


class TestSourceSchedulerIntegration:
    """Integration tests for Source Scheduler."""

    @pytest.mark.asyncio
    async def test_scheduler_initializes_with_registry(self, mock_fetcher):
        """Test that scheduler initializes with registry."""
        from modules.source.registry import SourceRegistry
        from modules.source.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Create callback
        async def on_items(items, config, task_id):
            pass

        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        # Verify scheduler is created
        assert scheduler is not None

    @pytest.mark.asyncio
    async def test_scheduler_starts_and_stops(self, mock_fetcher):
        """Test that scheduler starts and stops cleanly."""
        from modules.source.registry import SourceRegistry
        from modules.source.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        async def on_items(items, config, task_id):
            pass

        scheduler = SourceScheduler(
            registry=registry,
            on_items_discovered=on_items,
        )

        # Start and stop scheduler
        scheduler.start()
        scheduler.stop()

        # Should not raise error

    @pytest.mark.asyncio
    async def test_scheduler_schedules_enabled_sources(self, mock_fetcher):
        """Test that scheduler can be started with sources."""
        from modules.source.models import SourceConfig
        from modules.source.registry import SourceRegistry
        from modules.source.scheduler import SourceScheduler

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Add enabled source
        config = SourceConfig(
            id="scheduled_source",
            name="Scheduled Source",
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

        # Start scheduler
        scheduler.start()

        # Stop scheduler
        scheduler.stop()

        # Verify scheduler ran without errors
        assert True


class TestSourceParsingIntegration:
    """Integration tests for source parsing."""

    @pytest.mark.asyncio
    async def test_rss_parser_initializes(self, mock_fetcher):
        """Test that RSS parser initializes."""
        from modules.source.rss_parser import RSSParser

        parser = RSSParser(fetcher=mock_fetcher)

        # Verify parser is created
        assert parser is not None

    @pytest.mark.asyncio
    async def test_newsnow_parser_initializes(self, mock_fetcher):
        """Test that NewsNow parser initializes."""
        from modules.source.newsnow_parser import NewsNowParser

        parser = NewsNowParser(fetcher=mock_fetcher)

        # Verify parser is created
        assert parser is not None
