# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Parsing submodule - Data source parsing implementations."""

from modules.ingestion.parsing.base import BaseSourceParser
from modules.ingestion.parsing.newsnow_parser import NewsNowParser
from modules.ingestion.parsing.plugin import (
    PluginMetadata,
    get_plugin,
    get_registered_plugins,
    scan_and_load_external_plugins,
    source_parser_plugin,
)
from modules.ingestion.parsing.registry import SourceRegistry
from modules.ingestion.parsing.rss_parser import RSSParser

__all__ = [
    "BaseSourceParser",
    "NewsNowParser",
    "PluginMetadata",
    "RSSParser",
    "SourceRegistry",
    "get_plugin",
    "get_registered_plugins",
    "scan_and_load_external_plugins",
    "source_parser_plugin",
]
