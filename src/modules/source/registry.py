"""Source registry for managing multiple news sources."""

from __future__ import annotations

from modules.fetcher.base import BaseFetcher
from modules.source.models import SourceConfig
from modules.source.base import BaseSourceParser
from modules.source.rss_parser import RSSParser
from core.observability.logging import get_logger

log = get_logger("source_registry")


class SourceRegistry:
    """Registry of news sources and their parsers.

    Manages source configurations and maps source types to parsers.

    Args:
        fetcher: BaseFetcher instance for RSS feed fetching.
    """

    def __init__(self, fetcher: BaseFetcher) -> None:
        self._sources: dict[str, SourceConfig] = {}
        self._parsers: dict[str, BaseSourceParser] = {}
        self._fetcher = fetcher
        self._register_default_parsers()

    def _register_default_parsers(self) -> None:
        """Register built-in source parsers."""
        self._parsers["rss"] = RSSParser(self._fetcher)

    def register_parser(self, source_type: str, parser: BaseSourceParser) -> None:
        """Register a custom source parser.

        Args:
            source_type: Source type identifier.
            parser: Parser instance for this source type.
        """
        self._parsers[source_type] = parser
        log.info("parser_registered", source_type=source_type)

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
        """Get the parser for a given source type."""
        return self._parsers.get(source_type)

    async def close(self) -> None:
        """Close all registered parsers."""
        for parser in self._parsers.values():
            if hasattr(parser, "close"):
                await parser.close()
