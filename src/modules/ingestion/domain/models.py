# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Ingestion domain data models.

This module contains unified data models for the ingestion domain,
consolidating models from source and collector modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class NewsItem:
    """Represents a single news item discovered from a source.

    Attributes:
        url: The article URL.
        title: The article title.
        source: Source identifier (e.g. RSS feed URL or name).
        source_host: The hostname of the source.
        pubDate: Publication date from the feed.
        description: Brief description/summary from the feed.
        body: Full article body text. When present (e.g. from content:encoded
            in RSS), the Crawler will use it directly without re-fetching the URL.
    """

    url: str
    title: str
    source: str = ""
    source_host: str = ""
    pubDate: datetime | None = None
    description: str = ""
    body: str = ""


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


@dataclass
class ArticleRaw:
    """Raw article content after crawling and content extraction.

    Attributes:
        url: The URL of the article.
        title: Extracted title.
        body: Extracted body text (via trafilatura).
        source: Source identifier.
        publish_time: Publication time from the feed.
        source_host: The hostname of the source.
        tier: Source tier (1=authoritative, 2+=general). Lower = more authoritative.
        description: Description/summary from RSS feed (fallback when body is empty).
    """

    url: str
    title: str
    body: str
    source: str = ""
    publish_time: datetime | None = None
    source_host: str = ""
    tier: int = 2
    description: str = ""
