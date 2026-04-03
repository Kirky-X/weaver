# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Domain submodule - Core data models for the ingestion domain.

This module provides unified data structures that flow through
the entire ingestion pipeline.
"""

from modules.ingestion.domain.models import (
    ArticleRaw,
    NewsItem,
    RawArticle,
    SourceConfig,
)
from modules.ingestion.domain.processor import DiscoveryProcessor

__all__ = [
    "ArticleRaw",
    "DiscoveryProcessor",
    "NewsItem",
    "RawArticle",
    "SourceConfig",
]
