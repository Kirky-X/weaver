# Copyright (c) 2026 KirkyX. All Rights Reserved
"""
内容摄入域模块

合并了原 collector、fetcher、source 模块，提供完整的内容摄入流程：
- 数据源发现和解析（RSS/API）
- URL 和标题去重
- 网页抓取（HTTPX/Crawl4AI）
- 源调度管理

公开 API:
- Deduplicator: URL 两级去重
- RetryQueue: 失败重试队列
- SimHashDeduplicator: 标题相似度去重
- SmartFetcher: 智能抓取器
- FetchError, CircuitOpenError: 抓取异常
- SourceRegistry: 源注册表
- RSSParser: RSS 解析器
- SourceScheduler: 源调度器
- Crawler: 网页爬虫
- NewsItem, RawArticle, SourceConfig: 数据模型
"""

# Crawling
from modules.ingestion.crawling import Crawler

# Deduplication
from modules.ingestion.deduplication import (
    Deduplicator,
    RetryQueue,
    SimHashDeduplicator,
    TitleItem,
)

# Domain models
from modules.ingestion.domain.models import (
    ArticleRaw,
    NewsItem,
    RawArticle,
    SourceConfig,
)

# Fetching
from modules.ingestion.fetching import (
    BaseFetcher,
    CircuitOpenError,
    Crawl4AIFetcher,
    FetchError,
    HostRateLimiter,
    HttpxFetcher,
    SmartFetcher,
)

# Parsing
from modules.ingestion.parsing import (
    BaseSourceParser,
    PluginMetadata,
    RSSParser,
    SourceRegistry,
    get_plugin,
    get_registered_plugins,
    load_plugins,
    source_parser_plugin,
)

# Scheduling
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
    "RawArticle",
    "RetryQueue",
    "SimHashDeduplicator",
    "SmartFetcher",
    "SourceConfig",
    "SourceConfigRepo",
    "SourceRegistry",
    # Scheduling
    "SourceScheduler",
    "TitleItem",
    "get_plugin",
    "get_registered_plugins",
    "load_plugins",
    "source_parser_plugin",
]
