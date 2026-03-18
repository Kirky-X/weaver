# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SourceRegistry."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_fetcher():
    """Mock fetcher."""
    return AsyncMock()


class TestSourceRegistryBasic:
    """Basic functionality tests for SourceRegistry."""

    def test_registry_initializes(self, mock_fetcher):
        """Test that registry initializes correctly."""
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        assert registry is not None
        assert registry._fetcher is not None

    def test_registry_has_default_parsers(self, mock_fetcher):
        """Test that registry has default parsers."""
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Should have RSS and NewsNow parsers
        assert "rss" in registry._parsers
        assert "newsnow" in registry._parsers

    def test_registry_add_source(self, mock_fetcher):
        """Test adding a source to registry."""
        from modules.source.models import SourceConfig
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )

        registry.add_source(config)

        sources = registry.list_sources()
        assert len(sources) >= 1


class TestSourceRegistryEdgeCases:
    """Edge case tests for SourceRegistry."""

    def test_registry_with_empty_list(self, mock_fetcher):
        """Test registry behavior with no sources."""
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        sources = registry.list_sources()
        assert isinstance(sources, list)

    def test_registry_list_enabled_only(self, mock_fetcher):
        """Test listing only enabled sources."""
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

        enabled_sources = registry.list_sources(enabled_only=True)

        # Should only return enabled sources
        assert all(s.enabled for s in enabled_sources)

    def test_registry_update_source(self, mock_fetcher):
        """Test updating an existing source."""
        from modules.source.models import SourceConfig
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        config1 = SourceConfig(
            id="test_source",
            name="Original Name",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config1)

        config2 = SourceConfig(
            id="test_source",
            name="Updated Name",
            url="https://example.com/feed",
            source_type="rss",
            enabled=False,
        )
        registry.add_source(config2)

        # Should update, not duplicate
        # Note: list_sources with enabled_only=True filters out disabled sources
        source = registry.get_source("test_source")
        assert source.name == "Updated Name"
        assert source.enabled is False


class TestSourceRegistryErrorHandling:
    """Error handling tests for SourceRegistry."""

    def test_registry_get_unknown_source(self, mock_fetcher):
        """Test getting an unknown source."""
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        source = registry.get_source("unknown_source")
        assert source is None

    def test_registry_remove_source(self, mock_fetcher):
        """Test removing a source."""
        from modules.source.models import SourceConfig
        from modules.source.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        config = SourceConfig(
            id="to_remove",
            name="To Remove",
            url="https://example.com/feed",
            source_type="rss",
            enabled=True,
        )
        registry.add_source(config)

        # Remove source
        registry.remove_source("to_remove")

        # Should be gone
        source = registry.get_source("to_remove")
        assert source is None
