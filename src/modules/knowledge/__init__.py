# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Knowledge module - Knowledge graph and search operations.

Consolidates graph_store and search modules:
- Entity resolution and relation normalization
- Community detection and reporting
- Multiple search modes (Local/Global/DRIFT/Hybrid)

公开 API:
- Neo4jWriter: Neo4j 图数据库写入器
- EntityResolver: 实体解析器
- RelationTypeNormalizer: 关系类型标准化器
- GlobalSearchEngine: 全局搜索引擎
- LocalSearchEngine: 本地搜索引擎
- HybridSearchEngine: 混合搜索引擎
- CommunityDetector: 社区检测器
- IncrementalCommunityUpdater: 增量社区更新器
"""

# Graph operations
from modules.knowledge.graph import (
    CommunityDetector,
    CommunityReportGenerator,
    EntityResolver,
    GraphMetrics,
    IncrementalCommunityUpdater,
    NameNormalizer,
    Neo4jWriter,
    RelationTypeNormalizer,
)

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
    # Graph operations
    "CommunityDetector",
    "CommunityReportGenerator",
    # Search operations
    "ContextBuilder",
    "EntityResolver",
    "GlobalContextBuilder",
    "GlobalSearchEngine",
    "GraphMetrics",
    "HybridSearchEngine",
    "IncrementalCommunityUpdater",
    "LocalContextBuilder",
    "LocalSearchEngine",
    "NameNormalizer",
    "Neo4jWriter",
    "RelationTypeNormalizer",
]
