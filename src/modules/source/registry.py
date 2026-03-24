# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Source registry for managing multiple news sources.

This module provides a registry for managing source configurations and their
parsers. It supports both built-in parsers and dynamically loaded plugins.

Usage:
    # Built-in parsers are auto-registered
    registry = SourceRegistry(fetcher)
    registry.add_source(config)
    parser = registry.get_parser(config.source_type)

    # Register custom parser
    registry.register_parser("custom", MyCustomParser(fetcher))

    # Load external plugins
    registry.load_plugins(["./plugins", "/opt/weaver/plugins"])
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.observability.logging import get_logger
from modules.fetcher.base import BaseFetcher
from modules.source.base import BaseSourceParser
from modules.source.models import SourceConfig
from modules.source.newsnow_parser import NewsNowParser
from modules.source.plugin import (
    PluginMetadata,
    discover_plugins_from_directory,
    get_registered_plugins,
    scan_and_load_external_plugins,
)
from modules.source.rss_parser import RSSParser

if TYPE_CHECKING:
    from modules.source.plugin import PluginMetadata

log = get_logger("source_registry")


class SourceRegistry:
    """Registry of news sources and their parsers.

    Manages source configurations and maps source types to parsers.
    Supports dynamic plugin loading for extensibility.

    Args:
        fetcher: BaseFetcher instance for RSS feed fetching.

    Attributes:
        plugins_discovered: List of loaded plugin names.
    """

    def __init__(self, fetcher: BaseFetcher) -> None:
        self._sources: dict[str, SourceConfig] = {}
        self._parsers: dict[str, BaseSourceParser] = {}
        self._parser_metadata: dict[str, PluginMetadata] = {}
        self._fetcher = fetcher
        self._plugins_discovered: list[str] = []
        self._register_default_parsers()

    def _register_default_parsers(self) -> None:
        """Register built-in source parsers."""
        from modules.source.plugin import PluginMetadata

        # RSS Parser
        self._parsers["rss"] = RSSParser(self._fetcher)
        self._parser_metadata["rss"] = PluginMetadata(
            name="builtin_rss",
            version="1.0.0",
            description="Standard RSS/Atom feed parser",
            supported_types=["rss", "atom"],
            capabilities=["incremental", "etag", "last_modified"],
        )

        # NewsNow Parser
        self._parsers["newsnow"] = NewsNowParser(self._fetcher)
        self._parser_metadata["newsnow"] = PluginMetadata(
            name="builtin_newsnow",
            version="1.0.0",
            description="NewsNow feed parser with special handling",
            supported_types=["newsnow"],
            capabilities=["incremental"],
        )

    def register_parser(
        self,
        source_type: str,
        parser: BaseSourceParser,
        metadata: PluginMetadata | None = None,
    ) -> None:
        """Register a source parser.

        Args:
            source_type: Source type identifier.
            parser: Parser instance for this source type.
            metadata: Optional plugin metadata.
        """
        self._parsers[source_type] = parser
        if metadata:
            self._parser_metadata[source_type] = metadata
        log.info("parser_registered", source_type=source_type)

    def register_parser_class(
        self,
        source_type: str,
        parser_class: type[BaseSourceParser],
        metadata: PluginMetadata | None = None,
    ) -> None:
        """Register a parser class (will be instantiated with fetcher).

        Args:
            source_type: Source type identifier.
            parser_class: Parser class (must accept fetcher in __init__).
            metadata: Optional plugin metadata.
        """
        parser = parser_class(self._fetcher)
        self.register_parser(source_type, parser, metadata)

    def add_source(self, config: SourceConfig) -> None:
        """Add or update a source configuration.

        Args:
            config: Source configuration to register.
        """
        self._sources[config.id] = config
        log.info("source_added", source_id=config.id, name=config.name)

    def remove_source(self, source_id: str) -> None:
        """Remove a source by ID.

        Args:
            source_id: The source ID to remove.
        """
        self._sources.pop(source_id, None)
        log.info("source_removed", source_id=source_id)

    def get_source(self, source_id: str) -> SourceConfig | None:
        """Get a source configuration by ID."""
        return self._sources.get(source_id)

    def list_sources(self, enabled_only: bool = True) -> list[SourceConfig]:
        """List all registered sources.

        Args:
            enabled_only: If True, only return enabled sources.

        Returns:
            List of source configurations.
        """
        sources = list(self._sources.values())
        if enabled_only:
            sources = [s for s in sources if s.enabled]
        return sources

    def get_parser(self, source_type: str) -> BaseSourceParser | None:
        """Get the parser for a given source type.

        Args:
            source_type: Source type identifier.

        Returns:
            Parser instance or None if not found.
        """
        return self._parsers.get(source_type)

    def get_parser_metadata(self, source_type: str) -> PluginMetadata | None:
        """Get metadata for a registered parser.

        Args:
            source_type: Source type identifier.

        Returns:
            Plugin metadata or None if not found.
        """
        return self._parser_metadata.get(source_type)

    def list_registered_types(self) -> list[str]:
        """List all registered source types.

        Returns:
            List of source type identifiers.
        """
        return list(self._parsers.keys())

    def list_parser_info(self) -> list[dict]:
        """Get information about all registered parsers.

        Returns:
            List of dictionaries with parser information.
        """
        result = []
        for source_type, parser in self._parsers.items():
            metadata = self._parser_metadata.get(source_type)
            result.append({
                "source_type": source_type,
                "class_name": parser.__class__.__name__,
                "metadata": {
                    "name": metadata.name if metadata else "unknown",
                    "version": metadata.version if metadata else "unknown",
                    "description": metadata.description if metadata else "",
                    "capabilities": metadata.capabilities if metadata else [],
                } if metadata else None,
            })
        return result

    def load_plugins(self, plugin_paths: list[str] | None = None) -> list[str]:
        """Load external parser plugins.

        Args:
            plugin_paths: List of directory paths to scan for plugins.
                          Defaults to paths in WEAVER_SOURCE_PLUGINS env var.

        Returns:
            List of loaded plugin names.
        """
        # First scan entry points
        discovered = discover_plugins_from_directory(plugin_paths[0]) if plugin_paths else []
        scan_and_load_external_plugins(plugin_paths)

        # Register discovered plugins
        registered = get_registered_plugins()
        for plugin_name, metadata in registered.items():
            if metadata.name not in self._parsers:
                log.info("registering_plugin", name=plugin_name)

        self._plugins_discovered = list(registered.keys())
        return self._plugins_discovered

    async def close(self) -> None:
        """Close all registered parsers."""
        for parser in self._parsers.values():
            if hasattr(parser, "close"):
                await parser.close()
