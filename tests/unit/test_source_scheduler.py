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
        from modules.ingestion.domain.models import SourceConfig
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
        from modules.ingestion.domain.models import SourceConfig
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
