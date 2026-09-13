# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Shared ingestion domain models (NewsItem / RawArticle).

Owned by ``core.types`` since T021: these dataclasses flow through
processing and storage, so their canonical home must be outside the
``modules`` package to keep module import directions acyclic.
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
        source_id: The SourceConfig.id this item originated from (e.g. "rss-cnbeta").
        publish_time: Publication date from the feed.
        description: Brief description/summary from the feed.
        body: Full article body text. When present (e.g. from content:encoded
            in RSS), the Crawler will use it directly without re-fetching.
    """

    url: str
    title: str
    source: str = ""
    source_host: str = ""
    source_id: str | None = None
    publish_time: datetime | None = None
    description: str = ""
    body: str = ""


@dataclass
class RawArticle(NewsItem):
    """Raw article content after crawling and content extraction.

    Inherits from NewsItem and adds crawling-specific metadata.

    Attributes:
        body: Extracted body text (via trafilatura).
        html: Raw HTML content preserved for re-extraction by Cleaner.
        tier: Source tier (1=authoritative, 2+=general). Lower = more authoritative.
        crawl_status: Status of the crawl operation.
        crawl_error: Error message if crawl failed.
    """

    # Override body to be required (no empty default for crawled articles)
    body: str = ""
    html: str | None = None
    tier: int = 2
    crawl_status: str = "pending"
    crawl_error: str | None = None
