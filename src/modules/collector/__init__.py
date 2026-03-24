# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Collector module - Web crawling and content collection.

Public API:
- Deduplicator: URL deduplication using Redis
- RetryQueue: Retry queue management for failed crawl tasks
- Crawler: Main web crawler implementation (import directly)

Internal components (private, not exported):
- models: Data models for article collection
- processor: Article processing logic
- interleaver: Feed interleaving utilities
"""

from modules.collector.deduplicator import Deduplicator
from modules.collector.retry import RetryQueue

__all__ = [
    "Deduplicator",
    "RetryQueue",
]

# Note: Crawler should be imported directly when needed to avoid circular imports
# Usage: from modules.collector.crawler import Crawler
