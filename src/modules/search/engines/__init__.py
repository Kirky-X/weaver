# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Search engines for knowledge graph querying."""

from modules.search.engines.global_search import GlobalSearchEngine, MapReduceResult
from modules.search.engines.local_search import LocalSearchEngine, SearchResult

__all__ = [
    "GlobalSearchEngine",
    "LocalSearchEngine",
    "MapReduceResult",
    "SearchResult",
]
