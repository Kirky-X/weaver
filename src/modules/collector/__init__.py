# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Collector module - Web crawling and content collection.

Note: Import specific modules directly to avoid circular imports:
    from modules.collector.crawler import Crawler
    from modules.collector.models import ArticleRaw
"""

from modules.collector.deduplicator import Deduplicator
from modules.collector.retry import RetryQueue

__all__ = [
    "Deduplicator",
    "RetryQueue",
]
