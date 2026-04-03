# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Crawling submodule - Web crawling and content extraction."""

from modules.ingestion.crawling.crawler import Crawler

__all__ = [
    "Crawler",
]

# Note: For backward compatibility, ArticleRaw is available from domain module:
# from modules.ingestion.domain.models import ArticleRaw
