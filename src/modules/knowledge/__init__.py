# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge module - Knowledge graph domain.

This module consolidates knowledge graph functionality:
- core: Shared abstractions and data models
- graph: Graph building and management (formerly graph_store core)
- community: Community detection and reporting
- search: Search engines (formerly search)
- metrics: Graph metrics
"""

# Internal imports from submodules
from modules.knowledge.community import (
    Community,
    CommunityDetector,
    CommunityReport,
    CommunityReportGenerator,
    IncrementalCommunityUpdater,
    IncrementalUpdateResult,
    Neo4jCommunityRepo,
)
from modules.knowledge.core import NormalizedRelation, RelationTypeNormalizer
from modules.knowledge.graph import (
    EntityResolutionRules,
    EntityResolver,
    EntityType,
    GraphPruner,
    MatchType,
    NameNormalizer,
    Neo4jWriter,
    PruneResult,
    ResolutionResult,
    ResolutionRule,
)
from modules.knowledge.metrics import GraphMetrics
from modules.knowledge.search import (
    ContextBuilder,
    GlobalContextBuilder,
    GlobalSearchEngine,
    LocalContextBuilder,
    LocalSearchEngine,
    MapReduceResult,
    SearchResult,
)

__all__ = [
    "Community",
    "CommunityDetector",
    "CommunityReport",
    "CommunityReportGenerator",
    "ContextBuilder",
    "EntityResolutionRules",
    "EntityResolver",
    "EntityType",
    "GlobalContextBuilder",
    "GlobalSearchEngine",
    "GraphMetrics",
    "GraphPruner",
    "IncrementalCommunityUpdater",
    "IncrementalUpdateResult",
    "LocalContextBuilder",
    "LocalSearchEngine",
    "MapReduceResult",
    "MatchType",
    "NameNormalizer",
    "Neo4jCommunityRepo",
    "Neo4jWriter",
    "NormalizedRelation",
    "PruneResult",
    "RelationTypeNormalizer",
    "ResolutionResult",
    "ResolutionRule",
    "SearchResult",
]
