# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge module - Knowledge graph and search operations.

Consolidates graph_store and search modules:
- Entity resolution and relation normalization
- Community detection and reporting
- Multiple search modes (Local/Global/DRIFT/Hybrid)
"""

# Graph operations
from modules.knowledge.graph import (
    EntityResolver,
    GraphMetrics,
    IncrementalCommunityUpdater,
    NameNormalizer,
    Neo4jWriter,
    RelationTypeNormalizer,
)
from modules.knowledge.graph.community_detector import CommunityDetector
from modules.knowledge.graph.community_report_generator import CommunityReportGenerator

# Search operations
from modules.knowledge.search import (
    ContextBuilder,
    GlobalContextBuilder,
    GlobalSearchEngine,
    LocalContextBuilder,
    LocalSearchEngine,
)
from modules.knowledge.search.engines.hybrid_search import HybridSearchEngine

__all__ = [
    # Community
    "CommunityDetector",
    "CommunityReportGenerator",
    "ContextBuilder",
    "EntityResolver",
    "GlobalContextBuilder",
    "GlobalSearchEngine",
    # Metrics
    "GraphMetrics",
    "HybridSearchEngine",
    "IncrementalCommunityUpdater",
    "LocalContextBuilder",
    # Search
    "LocalSearchEngine",
    "NameNormalizer",
    # Graph operations
    "Neo4jWriter",
    "RelationTypeNormalizer",
]
