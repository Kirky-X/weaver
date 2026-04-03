# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Collector module - Web crawling and content collection.

.. deprecated:: 0.3.0
    Deduplicator and RetryQueue have moved to modules.ingestion.deduplication.

    Migration:
        # OLD
        from modules.collector import Deduplicator, RetryQueue

        # NEW
        from modules.ingestion.deduplication import Deduplicator, RetryQueue
"""

# Re-export from ingestion.deduplication for backward compatibility
from modules.ingestion.deduplication import Deduplicator, RetryQueue

__all__ = [
    "Deduplicator",
    "RetryQueue",
]

# Note: Crawler should be imported directly when needed to avoid circular imports
# Usage: from modules.collector.crawler import Crawler
