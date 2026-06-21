# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Search engines for knowledge graph querying."""

from modules.knowledge.search.engines.global_search import GlobalSearchEngine, MapReduceResult
from modules.knowledge.search.engines.hybrid_search import (
    HybridSearchConfig,
    HybridSearchEngine,
    HybridSearchResult,
)
from modules.knowledge.search.engines.local_search import LocalSearchEngine, SearchResult

__all__ = [
    "GlobalSearchEngine",
    "HybridSearchConfig",
    "HybridSearchEngine",
    "HybridSearchResult",
    "LocalSearchEngine",
    "MapReduceResult",
    "SearchResult",
]
