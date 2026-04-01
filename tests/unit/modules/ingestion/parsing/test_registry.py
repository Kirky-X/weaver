# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for SourceRegistry."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSourceRegistryInit:
    """Tests for SourceRegistry initialization."""

    def test_init_registers_default_parsers(self):
        """Test SourceRegistry registers default parsers."""
        from modules.ingestion.parsing.registry import SourceRegistry

        mock_fetcher = MagicMock()
        registry = SourceRegistry(fetcher=mock_fetcher)

        assert "rss" in registry.list_registered_types()
        assert "newsnow" in registry.list_registered_types()


class TestSourceRegistryRegisterParser:
    """Tests for register_parser()."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_register_parser_adds_parser(self, registry):
        """Test register_parser adds parser."""
        mock_parser = MagicMock()

        registry.register_parser("custom", mock_parser)

        assert registry.get_parser("custom") is mock_parser

    def test_register_parser_with_metadata(self, registry):
        """Test register_parser stores metadata."""
        from modules.ingestion.parsing.plugin import PluginMetadata

        mock_parser = MagicMock()
        metadata = PluginMetadata(
            name="custom_plugin",
            version="1.0.0",
            description="Custom parser",
            supported_types=["custom"],
            capabilities=[],
        )

        registry.register_parser("custom", mock_parser, metadata)

        assert registry.get_parser_metadata("custom") is metadata


class TestSourceRegistryRegisterParserClass:
    """Tests for register_parser_class()."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_register_parser_class_instantiates_with_fetcher(self, registry):
        """Test register_parser_class instantiates with fetcher."""
        from modules.ingestion.parsing.base import BaseSourceParser

        mock_parser = MagicMock(spec=BaseSourceParser)
        MockParserClass = MagicMock(return_value=mock_parser)

        registry.register_parser_class("custom_class", MockParserClass)

        MockParserClass.assert_called_once_with(registry._fetcher)
        assert registry.get_parser("custom_class") is mock_parser


class TestSourceRegistrySourceManagement:
    """Tests for source management methods."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_add_source(self, registry):
        """Test add_source registers source."""
        from modules.ingestion.domain.models import SourceConfig

        config = SourceConfig(
            id="source-1",
            name="Test Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
        )

        registry.add_source(config)

        assert registry.get_source("source-1") is config

    def test_remove_source(self, registry):
        """Test remove_source removes source."""
        from modules.ingestion.domain.models import SourceConfig

        config = SourceConfig(
            id="source-1",
            name="Test Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
        )

        registry.add_source(config)
        registry.remove_source("source-1")

        assert registry.get_source("source-1") is None

    def test_list_sources_enabled_only(self, registry):
        """Test list_sources filters by enabled."""
        from modules.ingestion.domain.models import SourceConfig

        enabled_config = SourceConfig(
            id="source-1",
            name="Enabled Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
            enabled=True,
        )
        disabled_config = SourceConfig(
            id="source-2",
            name="Disabled Source",
            source_type="rss",
            url="https://example.com/feed2",
            interval_minutes=30,
            enabled=False,
        )

        registry.add_source(enabled_config)
        registry.add_source(disabled_config)

        sources = registry.list_sources(enabled_only=True)

        assert len(sources) == 1
        assert sources[0].id == "source-1"

    def test_list_sources_all(self, registry):
        """Test list_sources returns all when enabled_only=False."""
        from modules.ingestion.domain.models import SourceConfig

        enabled_config = SourceConfig(
            id="source-1",
            name="Enabled Source",
            source_type="rss",
            url="https://example.com/feed",
            interval_minutes=30,
            enabled=True,
        )
        disabled_config = SourceConfig(
            id="source-2",
            name="Disabled Source",
            source_type="rss",
            url="https://example.com/feed2",
            interval_minutes=30,
            enabled=False,
        )

        registry.add_source(enabled_config)
        registry.add_source(disabled_config)

        sources = registry.list_sources(enabled_only=False)

        assert len(sources) == 2


class TestSourceRegistryParserInfo:
    """Tests for parser info methods."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    def test_list_registered_types(self, registry):
        """Test list_registered_types returns all types."""
        types = registry.list_registered_types()

        assert "rss" in types
        assert "newsnow" in types

    def test_list_parser_info(self, registry):
        """Test list_parser_info returns parser details."""
        info = registry.list_parser_info()

        assert len(info) >= 2  # rss and newsnow

        rss_info = next((i for i in info if i["source_type"] == "rss"), None)
        assert rss_info is not None
        assert rss_info["class_name"] == "RSSParser"
        assert rss_info["metadata"] is not None


class TestSourceRegistryClose:
    """Tests for close()."""

    @pytest.fixture
    def registry(self):
        """Create SourceRegistry instance."""
        from modules.ingestion.parsing.registry import SourceRegistry

        return SourceRegistry(fetcher=MagicMock())

    @pytest.mark.asyncio
    async def test_close_calls_parser_close(self, registry):
        """Test close() calls close on parsers with close method."""
        mock_parser = MagicMock()
        mock_parser.close = AsyncMock()

        registry.register_parser("custom", mock_parser)

        await registry.close()

        mock_parser.close.assert_called_once()
