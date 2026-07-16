# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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

from modules.ingestion.domain.models import NewsItem, SourceConfig
from modules.ingestion.parsing.base import BaseSourceParser
from modules.ingestion.parsing.newsnow_parser import NewsNowParser
from modules.ingestion.parsing.plugin import (
    PluginMetadata,
    get_plugin,
    get_registered_plugins,
    load_plugins,
    source_parser_plugin,
)
from modules.ingestion.parsing.registry import SourceRegistry
from modules.ingestion.parsing.rss_parser import RSSParser

__all__ = [
    "BaseSourceParser",
    "NewsItem",
    "NewsNowParser",
    "PluginMetadata",
    "RSSParser",
    "SourceConfig",
    "SourceRegistry",
    "get_plugin",
    "get_registered_plugins",
    "load_plugins",
    "source_parser_plugin",
]
