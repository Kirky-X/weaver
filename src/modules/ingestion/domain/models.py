# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unified data models for the ingestion domain.

This module provides the core data structures that flow through
the entire ingestion pipeline:
- NewsItem: Items discovered from RSS/API sources
- RawArticle: Articles after crawling and content extraction
- SourceConfig: Configuration for data sources
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class NewsItem:
    """Represents a single news item discovered from a source.

    This is the primary data structure for items found via RSS feeds
    or API endpoints before crawling.

    Attributes:
        url: The article URL.
        title: The article title.
        source: Source identifier (e.g. RSS feed URL or name).
        source_host: The hostname of the source.
        pubDate: Publication date from the feed.
        description: Brief description/summary from the feed.
        body: Full article body text. When present (e.g. from content:encoded
            in RSS), the Crawler will use it directly without re-fetching.
    """

    url: str
    title: str
    source: str = ""
    source_host: str = ""
    pubDate: datetime | None = None
    description: str = ""
    body: str = ""


@dataclass
class RawArticle(NewsItem):
    """Raw article content after crawling and content extraction.

    Inherits from NewsItem and adds crawling-specific metadata.

    Attributes:
        body: Extracted body text (via trafilatura).
        tier: Source tier (1=authoritative, 2+=general). Lower = more authoritative.
        crawl_status: Status of the crawl operation.
        crawl_error: Error message if crawl failed.
        publish_time: Alias for pubDate for backward compatibility.
    """

    # Override body to be required (no empty default for crawled articles)
    body: str = ""
    tier: int = 2
    crawl_status: str = "pending"
    crawl_error: str | None = None
    # Backward compatible field - syncs with pubDate via __post_init__
    publish_time: datetime | None = None

    def __post_init__(self) -> None:
        """Sync publish_time with pubDate."""
        if self.pubDate is None and self.publish_time is not None:
            self.pubDate = self.publish_time
        elif self.pubDate is not None and self.publish_time is None:
            self.publish_time = self.pubDate


@dataclass
class SourceConfig:
    """Configuration for a news source.

    Attributes:
        id: Unique source identifier.
        name: Human-readable name.
        url: Feed URL (RSS/Atom).
        source_type: Type of source (rss, api, etc.).
        enabled: Whether the source is active.
        interval_minutes: Crawl interval.
        per_host_concurrency: Max concurrent requests to this host.
        credibility: Preset credibility score (0.0-1.0), overrides auto-calculated.
        tier: Source tier (1=authoritative, 2=credible, 3=ordinary).
        last_crawl_time: Last successful crawl timestamp.
        etag: HTTP ETag for conditional requests.
        last_modified: HTTP Last-Modified header.
    """

    id: str
    name: str
    url: str
    source_type: str = "rss"
    enabled: bool = True
    interval_minutes: int = 30
    per_host_concurrency: int = 2
    credibility: float | None = None
    tier: int | None = None
    last_crawl_time: datetime | None = None
    etag: str | None = None
    last_modified: str | None = None

    def __post_init__(self) -> None:
        """Validate field ranges after initialization."""
        if self.credibility is not None:
            if not (0.0 <= self.credibility <= 1.0):
                raise ValueError(f"credibility must be in range [0.0, 1.0], got {self.credibility}")
        if self.tier is not None:
            if not (1 <= self.tier <= 3):
                raise ValueError(f"tier must be in range [1, 3], got {self.tier}")


# Backward compatibility: ArticleRaw alias for RawArticle
# (matches original collector/models.py naming)
ArticleRaw = RawArticle
