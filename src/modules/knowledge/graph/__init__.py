# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge graph module - Neo4j graph database operations."""

from modules.knowledge.graph.entity_resolver import EntityResolver
from modules.knowledge.graph.incremental_community_updater import (
    IncrementalCommunityUpdater,
    IncrementalUpdateResult,
)
from modules.knowledge.graph.metrics import GraphMetrics
from modules.knowledge.graph.name_normalizer import NameNormalizer
from modules.knowledge.graph.neo4j_writer import Neo4jWriter
from modules.knowledge.graph.relation_type_normalizer import (
    NormalizedRelation,
    RelationTypeNormalizer,
)
from modules.knowledge.graph.resolution_rules import (
    EntityResolutionRules,
    EntityType,
    MatchType,
    ResolutionResult,
    ResolutionRule,
)

__all__ = [
    "EntityResolutionRules",
    "EntityResolver",
    "EntityType",
    "GraphMetrics",
    "IncrementalCommunityUpdater",
    "IncrementalUpdateResult",
    "MatchType",
    "NameNormalizer",
    "Neo4jWriter",
    "NormalizedRelation",
    "RelationTypeNormalizer",
    "ResolutionResult",
    "ResolutionRule",
]
