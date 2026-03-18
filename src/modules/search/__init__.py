# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Search module - Local and global search engines."""

from modules.search.context.builder import ContextBuilder
from modules.search.context.global_context import GlobalContextBuilder
from modules.search.context.local_context import LocalContextBuilder
from modules.search.engines.global_search import GlobalSearchEngine, MapReduceResult
from modules.search.engines.local_search import LocalSearchEngine, SearchResult

__all__ = [
    "ContextBuilder",
    "GlobalContextBuilder",
    "GlobalSearchEngine",
    "LocalContextBuilder",
    "LocalSearchEngine",
    "MapReduceResult",
    "SearchResult",
]
