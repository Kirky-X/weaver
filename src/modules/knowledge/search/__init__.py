# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Search module - Local and global search engines."""

from modules.knowledge.search.context.builder import ContextBuilder
from modules.knowledge.search.context.global_context import GlobalContextBuilder
from modules.knowledge.search.context.local_context import LocalContextBuilder
from modules.knowledge.search.engines.drift_search import DRIFTSearchEngine
from modules.knowledge.search.engines.global_search import GlobalSearchEngine, MapReduceResult
from modules.knowledge.search.engines.hybrid_search import (
    HybridSearchConfig,
    HybridSearchEngine,
)
from modules.knowledge.search.engines.local_search import LocalSearchEngine, SearchResult
from modules.knowledge.search.intent.router import IntentRouter, RoutingConfig
from modules.knowledge.search.intent.schemas import IntentClassification, QueryIntent

__all__ = [
    "ContextBuilder",
    "DRIFTSearchEngine",
    "GlobalContextBuilder",
    "GlobalSearchEngine",
    "HybridSearchConfig",
    "HybridSearchEngine",
    "IntentClassification",
    "IntentRouter",
    "LocalContextBuilder",
    "LocalSearchEngine",
    "MapReduceResult",
    "QueryIntent",
    "RoutingConfig",
    "SearchResult",
]
