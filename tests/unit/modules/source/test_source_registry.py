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
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        assert registry is not None
        assert registry._fetcher is not None

    def test_registry_has_default_parsers(self, mock_fetcher):
        """Test that registry has default parsers."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Should have RSS and NewsNow parsers
        assert "rss" in registry._parsers
        assert "newsnow" in registry._parsers

    def test_registry_add_source(self, mock_fetcher):
        """Test adding a source to registry."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry

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
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        sources = registry.list_sources()
        assert isinstance(sources, list)

    def test_registry_list_enabled_only(self, mock_fetcher):
        """Test listing only enabled sources."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry

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
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry

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
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        source = registry.get_source("unknown_source")
        assert source is None

    def test_registry_remove_source(self, mock_fetcher):
        """Test removing a source."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry

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


class TestSourceRegistryParserMethods:
    """Tests for parser-related methods."""

    def test_get_parser(self, mock_fetcher):
        """Test getting a parser by source type."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        parser = registry.get_parser("rss")
        assert parser is not None

    def test_get_parser_unknown_type(self, mock_fetcher):
        """Test getting a parser for unknown type."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        parser = registry.get_parser("unknown_type")
        assert parser is None

    def test_get_parser_metadata(self, mock_fetcher):
        """Test getting parser metadata."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        metadata = registry.get_parser_metadata("rss")
        assert metadata is not None
        assert metadata.name == "builtin_rss"

    def test_get_parser_metadata_unknown(self, mock_fetcher):
        """Test getting metadata for unknown parser."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        metadata = registry.get_parser_metadata("unknown")
        assert metadata is None

    def test_list_registered_types(self, mock_fetcher):
        """Test listing all registered types."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        types = registry.list_registered_types()
        assert "rss" in types
        assert "newsnow" in types

    def test_list_parser_info(self, mock_fetcher):
        """Test listing parser information."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        info = registry.list_parser_info()
        assert len(info) >= 2
        rss_info = next((i for i in info if i["source_type"] == "rss"), None)
        assert rss_info is not None
        assert rss_info["class_name"] == "RSSParser"
        assert rss_info["metadata"]["name"] == "builtin_rss"


class TestSourceRegistryCustomParser:
    """Tests for custom parser registration."""

    def test_register_parser(self, mock_fetcher):
        """Test registering a custom parser."""
        from modules.ingestion.parsing.base import BaseSourceParser
        from modules.ingestion.parsing.registry import SourceRegistry

        class CustomParser(BaseSourceParser):
            async def parse(self, config):
                return []

        registry = SourceRegistry(fetcher=mock_fetcher)
        custom_parser = CustomParser()

        registry.register_parser("custom", custom_parser)

        parser = registry.get_parser("custom")
        assert parser is custom_parser

    def test_register_parser_with_metadata(self, mock_fetcher):
        """Test registering a parser with metadata."""
        from modules.ingestion.parsing.base import BaseSourceParser
        from modules.ingestion.parsing.plugin import PluginMetadata
        from modules.ingestion.parsing.registry import SourceRegistry

        class CustomParser(BaseSourceParser):
            async def parse(self, config):
                return []

        registry = SourceRegistry(fetcher=mock_fetcher)
        custom_parser = CustomParser()
        metadata = PluginMetadata(
            name="custom_parser",
            version="1.0.0",
            description="Custom parser for testing",
            supported_types=["custom"],
            capabilities=[],
        )

        registry.register_parser("custom", custom_parser, metadata)

        stored_metadata = registry.get_parser_metadata("custom")
        assert stored_metadata is not None
        assert stored_metadata.name == "custom_parser"

    def test_register_parser_class(self, mock_fetcher):
        """Test registering a parser class."""
        from modules.ingestion.parsing.base import BaseSourceParser
        from modules.ingestion.parsing.registry import SourceRegistry

        class CustomParser(BaseSourceParser):
            def __init__(self, fetcher):
                self.custom_init = True

            async def parse(self, config):
                return []

        registry = SourceRegistry(fetcher=mock_fetcher)

        registry.register_parser_class("custom_class", CustomParser)

        parser = registry.get_parser("custom_class")
        assert parser is not None
        assert hasattr(parser, "custom_init")

    def test_register_parser_class_with_metadata(self, mock_fetcher):
        """Test registering a parser class with metadata."""
        from modules.ingestion.parsing.base import BaseSourceParser
        from modules.ingestion.parsing.plugin import PluginMetadata
        from modules.ingestion.parsing.registry import SourceRegistry

        class CustomParser(BaseSourceParser):
            def __init__(self, fetcher):
                pass

            async def parse(self, config):
                return []

        registry = SourceRegistry(fetcher=mock_fetcher)
        metadata = PluginMetadata(
            name="custom_class_parser",
            version="2.0.0",
            description="Custom class parser",
            supported_types=["custom_class"],
            capabilities=[],
        )

        registry.register_parser_class("custom_class", CustomParser, metadata)

        stored_metadata = registry.get_parser_metadata("custom_class")
        assert stored_metadata.name == "custom_class_parser"


class TestSourceRegistryPlugins:
    """Tests for plugin loading."""

    def test_load_plugins_returns_list(self, mock_fetcher):
        """Test that load_plugins returns a list."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        result = registry.load_plugins()
        assert isinstance(result, list)


class TestSourceRegistryAsyncMethods:
    """Tests for async methods."""

    @pytest.mark.asyncio
    async def test_close_calls_parser_close(self, mock_fetcher):
        """Test that close calls close on parsers that have it."""
        from unittest.mock import AsyncMock

        from modules.ingestion.parsing.base import BaseSourceParser
        from modules.ingestion.parsing.registry import SourceRegistry

        class CloseableParser(BaseSourceParser):
            def __init__(self, fetcher=None):
                self.close = AsyncMock()

            async def parse(self, config):
                return []

        registry = SourceRegistry(fetcher=mock_fetcher)
        closeable = CloseableParser()
        registry.register_parser("closeable", closeable)

        await registry.close()

        closeable.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_handles_parser_without_close(self, mock_fetcher):
        """Test that close handles parsers without close method."""
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        # Should not raise
        await registry.close()


class TestSourceRegistryListSources:
    """Tests for list_sources method."""

    def test_list_sources_returns_all_by_default(self, mock_fetcher):
        """Test that list_sources returns only enabled sources by default."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        config1 = SourceConfig(
            id="enabled1",
            name="Enabled 1",
            url="https://example.com/feed1",
            source_type="rss",
            enabled=True,
        )
        config2 = SourceConfig(
            id="enabled2",
            name="Enabled 2",
            url="https://example.com/feed2",
            source_type="rss",
            enabled=True,
        )
        config3 = SourceConfig(
            id="disabled",
            name="Disabled",
            url="https://example.com/feed3",
            source_type="rss",
            enabled=False,
        )

        registry.add_source(config1)
        registry.add_source(config2)
        registry.add_source(config3)

        sources = registry.list_sources()  # enabled_only=True by default
        assert len(sources) == 2
        assert all(s.enabled for s in sources)

    def test_list_sources_all(self, mock_fetcher):
        """Test listing all sources including disabled."""
        from modules.ingestion.parsing.models import SourceConfig
        from modules.ingestion.parsing.registry import SourceRegistry

        registry = SourceRegistry(fetcher=mock_fetcher)

        config1 = SourceConfig(
            id="enabled",
            name="Enabled",
            url="https://example.com/feed1",
            source_type="rss",
            enabled=True,
        )
        config2 = SourceConfig(
            id="disabled",
            name="Disabled",
            url="https://example.com/feed2",
            source_type="rss",
            enabled=False,
        )

        registry.add_source(config1)
        registry.add_source(config2)

        sources = registry.list_sources(enabled_only=False)
        assert len(sources) == 2
