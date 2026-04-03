# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Domain submodule - Core data models for the ingestion domain.

This module provides unified data structures that flow through
the entire ingestion pipeline.

Note: DiscoveryProcessor is intentionally NOT exported here to avoid
circular imports. Import it directly from modules.ingestion.domain.processor
"""

from modules.ingestion.domain.models import (
    ArticleRaw,
    NewsItem,
    RawArticle,
    SourceConfig,
)

__all__ = [
    "ArticleRaw",
    "NewsItem",
    "RawArticle",
    "SourceConfig",
]
