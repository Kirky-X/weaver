# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Parsing submodule - RSS feed and data source management.

This module provides:
- Built-in parsers: RSS, NewsNow
- Plugin system for custom parsers
- Source registry for managing sources and parsers

Example plugin usage:

    from modules.ingestion.parsing.plugin import source_parser_plugin, PluginMetadata

    @source_parser_plugin(
        name="my_custom_parser",
        supported_types=["custom_type"],
        capabilities=["streaming"]
    )
    class MyCustomParser(BaseSourceParser):
        ...
"""

from modules.ingestion.parsing.base import BaseSourceParser
from modules.ingestion.parsing.models import NewsItem, SourceConfig
from modules.ingestion.parsing.plugin import (
    PluginMetadata,
    get_plugin,
    get_registered_plugins,
    scan_and_load_external_plugins as _scan_plugins,
    source_parser_plugin,
)
from modules.ingestion.parsing.registry import SourceRegistry
from modules.ingestion.parsing.rss_parser import RSSParser

__all__ = [
    "BaseSourceParser",
    "NewsItem",
    "PluginMetadata",
    "RSSParser",
    "SourceRegistry",
    "get_plugin",
    "get_registered_plugins",
    "load_plugins",
    "source_parser_plugin",
]


def load_plugins(plugin_paths: list[str] | None = None) -> list[str]:
    """Load external parser plugins.

    Args:
        plugin_paths: Optional list of directory paths to scan.

    Returns:
        List of loaded plugin names.
    """
    _scan_plugins(plugin_paths)
    return list(get_registered_plugins().keys())
