# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Source module - RSS feed and data source management.

This module provides:
- Built-in parsers: RSS, NewsNow
- Plugin system for custom parsers
- Source registry for managing sources and parsers

Example plugin usage:

    from modules.source.plugin import source_parser_plugin, PluginMetadata

    @source_parser_plugin(
        name="my_custom_parser",
        supported_types=["custom_type"],
        capabilities=["streaming"]
    )
    class MyCustomParser(BaseSourceParser):
        ...
"""

from modules.source.base import BaseSourceParser
from modules.source.models import NewsItem, SourceConfig
from modules.source.plugin import (
    PluginMetadata,
    get_plugin,
    get_registered_plugins,
    scan_and_load_external_plugins as _scan_plugins,
    source_parser_plugin,
)
from modules.source.registry import SourceRegistry
from modules.source.rss_parser import RSSParser
from modules.source.scheduler import SourceScheduler
from modules.source.source_config_repo import SourceConfigRepo

__all__ = [
    # Base
    "BaseSourceParser",
    # Models
    "NewsItem",
    # Plugin system
    "PluginMetadata",
    # Core classes
    "RSSParser",
    "SourceConfig",
    "SourceConfigRepo",
    "SourceRegistry",
    "SourceScheduler",
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
