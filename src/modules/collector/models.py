# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Collector module data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
    """

    url: str
    title: str
    body: str
    source: str = ""
    publish_time: datetime | None = None
    source_host: str = ""
    tier: int = 2
