# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Ingestion module - Content ingestion domain.

This module consolidates content ingestion functionality:
- fetching: Web content fetching (formerly fetcher)
- parsing: Data source parsing (formerly source core)
- scheduling: Source scheduling (formerly source.scheduler)
- deduplication: URL/content deduplication (formerly collector core)
- crawling: Web crawling (formerly collector.crawler)
- domain: Unified data models (NewsItem, ArticleRaw, SourceConfig)
"""

# Internal imports from submodules
from modules.ingestion.crawling import Crawler
from modules.ingestion.deduplication import Deduplicator, RetryQueue, SimHashDeduplicator, TitleItem
from modules.ingestion.domain import ArticleRaw, NewsItem, SourceConfig
from modules.ingestion.fetching import (
    BaseFetcher,
    CircuitOpenError,
    Crawl4AIFetcher,
    FetchError,
    HostRateLimiter,
    HttpxFetcher,
    SmartFetcher,
)
from modules.ingestion.parsing import (
    BaseSourceParser,
    NewsNowParser,
    PluginMetadata,
    RSSParser,
    SourceRegistry,
    get_plugin,
    get_registered_plugins,
    scan_and_load_external_plugins,
    source_parser_plugin,
)
from modules.ingestion.scheduling import SourceConfigRepo, SourceScheduler

__all__ = [
    "ArticleRaw",
    "BaseFetcher",
    "BaseSourceParser",
    "CircuitOpenError",
    "Crawl4AIFetcher",
    "Crawler",
    "Deduplicator",
    "FetchError",
    "HostRateLimiter",
    "HttpxFetcher",
    "NewsItem",
    "NewsNowParser",
    "PluginMetadata",
    "RSSParser",
    "RetryQueue",
    "SimHashDeduplicator",
    "SmartFetcher",
    "SourceConfig",
    "SourceConfigRepo",
    "SourceRegistry",
    "SourceScheduler",
    "TitleItem",
    "get_plugin",
    "get_registered_plugins",
    "scan_and_load_external_plugins",
    "source_parser_plugin",
]


def load_plugins(plugin_paths: list[str] | None = None) -> list[str]:
    """Load external parser plugins.

    Args:
        plugin_paths: Optional list of directory paths to scan.

    Returns:
        List of loaded plugin names.
    """
    scan_and_load_external_plugins(plugin_paths)
    return list(get_registered_plugins().keys())
