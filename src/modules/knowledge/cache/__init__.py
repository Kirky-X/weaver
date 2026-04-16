# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge cluster caching module.

Provides DuckDB + Parquet based caching for semantic search results.
"""

from modules.knowledge.cache.storage import KnowledgeCache

__all__ = [
    "KnowledgeCache",
]
