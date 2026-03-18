# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Source module data models."""

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
    """

    url: str
    title: str
    source: str = ""
    source_host: str = ""
    pubDate: datetime | None = None
    description: str = ""


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
    """

    id: str
    name: str
    url: str
    source_type: str = "rss"
    enabled: bool = True
    interval_minutes: int = 30
    per_host_concurrency: int = 2
    last_crawl_time: datetime | None = None
    etag: str | None = None
    last_modified: str | None = None
