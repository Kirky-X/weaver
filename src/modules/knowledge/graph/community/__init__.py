"""Community sub-package - community detection, management, and reporting."""

from modules.knowledge.graph.community.detector import CommunityDetector
from modules.knowledge.graph.community.enums import ModularityMetric
from modules.knowledge.graph.community.models import (
    Community,
    CommunityDetectionResult,
    HierarchicalCluster,
)
from modules.knowledge.graph.community.modularity import (
    ModularityResult,
    calculate_modularity,
)
from modules.knowledge.graph.community.repair_service import CommunityRepairService
from modules.knowledge.graph.community.repo import Neo4jCommunityRepo
from modules.knowledge.graph.community.report_generator import (
    CommunityReportGenerator,
    CommunityReportOutput,
    ReportGenerationResult,
)
from modules.knowledge.graph.community.subgraph_extractor import SubgraphExtractor
from modules.knowledge.graph.community.updater import (
    CommunityStats,
    IncrementalCommunityUpdater,
    IncrementalUpdateResult,
)

__all__ = [
    "Community",
    "CommunityDetectionResult",
    "CommunityDetector",
    "CommunityRepairService",
    "CommunityReportGenerator",
    "CommunityReportOutput",
    "CommunityStats",
    "HierarchicalCluster",
    "IncrementalCommunityUpdater",
    "IncrementalUpdateResult",
    "ModularityMetric",
    "ModularityResult",
    "Neo4jCommunityRepo",
    "ReportGenerationResult",
    "SubgraphExtractor",
    "calculate_modularity",
]
