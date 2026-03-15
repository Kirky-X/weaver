"""Search engines for knowledge graph querying."""

from modules.search.engines.local_search import LocalSearchEngine, SearchResult
from modules.search.engines.global_search import GlobalSearchEngine, MapReduceResult

__all__ = [
    "LocalSearchEngine",
    "GlobalSearchEngine", 
    "SearchResult",
    "MapReduceResult",
]
