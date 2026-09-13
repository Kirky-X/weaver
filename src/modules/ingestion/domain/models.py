# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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


# NewsItem / RawArticle moved to core.types.ingestion_models (T021:
# shared pipeline domain models must live in core so processing and
# storage can depend on them without modules-level import cycles).

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
        if not self.id or not self.id.strip():
            raise ValueError(f"id must be a non-empty string, got {self.id!r}")
        if self.credibility is not None:
            if not (0.0 <= self.credibility <= 1.0):
                raise ValueError(f"credibility must be in range [0.0, 1.0], got {self.credibility}")
        if self.tier is not None:
            if not (1 <= self.tier <= 3):
                raise ValueError(f"tier must be in range [1, 3], got {self.tier}")
