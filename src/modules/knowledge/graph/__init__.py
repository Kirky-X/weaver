# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge graph module - Neo4j graph database operations."""

# Community detection and management
from modules.knowledge.graph.community_detector import CommunityDetector
from modules.knowledge.graph.community_health_checker import CommunityHealthChecker
from modules.knowledge.graph.community_health_models import (
    CommunityHealthStatus,
    IssueType,
    RepairSummary,
)
from modules.knowledge.graph.community_repair_service import CommunityRepairService
from modules.knowledge.graph.community_repo import Neo4jCommunityRepo
from modules.knowledge.graph.community_report_generator import (
    CommunityReportGenerator,
    ReportGenerationResult,
)

# Entity resolution
from modules.knowledge.graph.entity_resolver import EntityResolver
from modules.knowledge.graph.incremental_community_updater import (
    IncrementalCommunityUpdater,
    IncrementalUpdateResult,
)
from modules.knowledge.graph.metrics import GraphMetrics, GraphQualityMetrics
from modules.knowledge.graph.name_normalizer import NameNormalizer, name_normalizer
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
    resolution_rules,
)

__all__ = [
    "CommunityDetector",
    "CommunityHealthChecker",
    "CommunityHealthStatus",
    "CommunityRepairService",
    "CommunityReportGenerator",
    "EntityResolutionRules",
    "EntityResolver",
    "EntityType",
    "GraphMetrics",
    "GraphQualityMetrics",
    "IncrementalCommunityUpdater",
    "IncrementalUpdateResult",
    "IssueType",
    "MatchType",
    "NameNormalizer",
    "Neo4jCommunityRepo",
    "Neo4jWriter",
    "NormalizedRelation",
    "RelationTypeNormalizer",
    "RepairSummary",
    "ReportGenerationResult",
    "ResolutionResult",
    "ResolutionRule",
    "name_normalizer",
    "resolution_rules",
]
