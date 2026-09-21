# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
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

from core.observability import get_logger
from modules.ingestion.domain.models import SourceConfig
from modules.ingestion.fetching.base import BaseFetcher
from modules.ingestion.parsing.base import BaseSourceParser
from modules.ingestion.parsing.document_parsers import (
    HTMLIndexParser,
    JSONApiParser,
    PDFDocumentParser,
)
from modules.ingestion.parsing.newsnow_parser import NewsNowParser
from modules.ingestion.parsing.plugin import (
    get_plugin,
    get_registered_plugins,
    scan_and_load_external_plugins,
)
from modules.ingestion.parsing.rss_parser import RSSParser

if TYPE_CHECKING:
    from modules.ingestion.parsing.plugin import PluginMetadata

log = get_logger(__name__)


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
        """Register built-in source parsers.

        Keys here are the single source of truth for "can this source type
        actually be crawled". ``core.constants.REGISTERED_TYPES`` mirrors this
        set for API-side validation, and
        ``tests/unit/modules/ingestion/parsing/test_registry.py`` asserts the
        two stay in sync — a divergence means a source type that is either
        rejected despite working, or accepted but silently never crawled.
        """
        from modules.ingestion.parsing.plugin import PluginMetadata

        # RSS Parser — registered under both "rss" and "atom". Both keys must
        # exist: get_parser() does an exact dict lookup, so an "atom" source
        # would otherwise be rejected as "no_parser_for_type" even though the
        # metadata advertises Atom support (RSSParser handles Atom natively
        # via feedparser). Both keys share one instance — the parser is
        # stateless apart from the fetcher.
        rss_parser = RSSParser(self._fetcher)
        rss_metadata = PluginMetadata(
            name="builtin_rss",
            version="1.0.0",
            description="Standard RSS/Atom feed parser",
            supported_types=["rss", "atom"],
            capabilities=["incremental", "etag", "last_modified"],
        )
        for source_type in ("rss", "atom"):
            self._parsers[source_type] = rss_parser
            self._parser_metadata[source_type] = rss_metadata

        # NewsNow Parser
        self._parsers["newsnow"] = NewsNowParser(self._fetcher)
        self._parser_metadata["newsnow"] = PluginMetadata(
            name="builtin_newsnow",
            version="1.0.0",
            description="NewsNow feed parser with special handling",
            supported_types=["newsnow"],
            capabilities=["incremental"],
        )

        # Document parsers — HTML index pages, JSON APIs, PDF documents.
        # Declared in core.constants.SourceType and accepted by the
        # create-source API, these were previously never registered here;
        # get_parser() is an exact dict lookup, so such sources hit
        # no_parser_for_type at crawl time and were silently never crawled.
        document_parsers: tuple[tuple[str, type[BaseSourceParser], str], ...] = (
            ("html", HTMLIndexParser, "HTML index page link extractor"),
            ("json", JSONApiParser, "Generic JSON list endpoint parser"),
            ("pdf", PDFDocumentParser, "PDF document text extractor"),
        )
        for source_type, parser_class, description in document_parsers:
            self._parsers[source_type] = parser_class(self._fetcher)
            self._parser_metadata[source_type] = PluginMetadata(
                name=f"builtin_{source_type}",
                version="1.0.0",
                description=description,
                supported_types=[source_type],
                capabilities=[],
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
            result.append(
                {
                    "source_type": source_type,
                    "class_name": parser.__class__.__name__,
                    "metadata": (
                        {
                            "name": metadata.name if metadata else "unknown",
                            "version": metadata.version if metadata else "unknown",
                            "description": metadata.description if metadata else "",
                            "capabilities": metadata.capabilities if metadata else [],
                        }
                        if metadata
                        else None
                    ),
                }
            )
        return result

    def load_plugins(self, plugin_paths: list[str] | None = None) -> list[str]:
        """Load external parser plugins.

        Discovered plugins are instantiated with the registry's fetcher and
        registered for every source type they declare in
        ``supported_types`` (falls back to the plugin name when empty).
        A single plugin that fails to instantiate is skipped with a
        warning so it cannot block the others.

        Args:
            plugin_paths: List of directory paths to scan for plugins.
                          Defaults to paths in WEAVER_SOURCE_PLUGINS env var.

        Returns:
            Plugin names discovered and processed for registration by this
            call (including plugins whose instantiation failed).
        """
        # scan_and_load_external_plugins already walks every path and calls
        # discover_plugins_from_directory internally — no separate
        # first-path discovery pass needed here.
        scan_and_load_external_plugins(plugin_paths)

        # Register discovered plugins — each registry entry carries the
        # parser class; instantiate and register per supported source type.
        registered = get_registered_plugins()
        processed: list[str] = []
        for plugin_name, metadata in registered.items():
            types_to_register = metadata.supported_types or [plugin_name]
            if all(t in self._parsers for t in types_to_register):
                continue
            processed.append(plugin_name)
            entry = get_plugin(plugin_name)
            if entry is None:
                log.warning("plugin_class_missing", name=plugin_name)
                continue
            parser_class, _plugin_meta = entry
            try:
                parser = parser_class(self._fetcher)
            except Exception as exc:
                log.warning(
                    "plugin_parser_instantiation_failed",
                    name=plugin_name,
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )
                continue
            for source_type in types_to_register:
                if source_type not in self._parsers:
                    self.register_parser(source_type, parser, metadata)

        self._plugins_discovered = sorted(set(processed))
        return self._plugins_discovered

    async def close(self) -> None:
        """Close all registered parsers.

        Each parser is closed in isolation: a failure in one parser is
        logged and must not prevent the remaining parsers from being
        cleaned up.
        """
        for parser in self._parsers.values():
            if hasattr(parser, "close"):
                try:
                    await parser.close()
                except Exception as exc:
                    log.warning(
                        "parser_close_failed",
                        parser=type(parser).__name__,
                        error=str(exc),
                        exc_type=type(exc).__name__,
                    )
