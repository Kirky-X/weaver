# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Deduplication submodule - URL and content deduplication."""

from modules.ingestion.deduplication.deduplicator import Deduplicator
from modules.ingestion.deduplication.retry import RetryQueue
from modules.ingestion.deduplication.simhash_dedup import SimHashDeduplicator, TitleItem

__all__ = [
    "Deduplicator",
    "RetryQueue",
    "SimHashDeduplicator",
    "TitleItem",
]
