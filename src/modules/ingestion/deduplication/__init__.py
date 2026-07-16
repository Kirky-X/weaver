# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Deduplication submodule - URL and title deduplication.

Public API:
- Deduplicator: URL deduplication using Redis
- SimHashDeduplicator: Title similarity deduplication
- RetryQueue: Retry queue management for failed crawl tasks
- TitleItem: Data class for title deduplication
"""

from modules.ingestion.deduplication.deduplicator import Deduplicator
from modules.ingestion.deduplication.models import TitleItem
from modules.ingestion.deduplication.retry import RetryQueue
from modules.ingestion.deduplication.simhash_dedup import SimHashDeduplicator

__all__ = [
    "Deduplicator",
    "RetryQueue",
    "SimHashDeduplicator",
    "TitleItem",
]
