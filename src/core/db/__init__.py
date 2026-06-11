# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core database module - PostgreSQL, Neo4j, DuckDB, and LadybugDB connection pools.

公开 API:
- PostgresPool: PostgreSQL 连接池
- Neo4jPool: Neo4j 连接池
- DuckDBPool: DuckDB 连接池
- LadybugPool: LadybugDB 连接池
- Article, PersistStatus: 数据库模型
- create_vector_query_builder: 向量查询构建器
"""

from core.db.duckdb_pool import DuckDBPool
from core.db.graph_query_builders import GraphDatabaseType
from core.db.initializer import (
    REQUIRED_NEO4J_CONSTRAINTS,
    REQUIRED_TABLES,
    DatabaseInitError,
    ParsedDSN,
    check_database_exists,
    create_database,
    initialize_database,
    initialize_neo4j,
    parse_dsn,
    run_migrations,
    verify_neo4j_constraints,
    verify_tables,
    wait_for_postgres,
)
from core.db.ladybug_pool import LadybugPool
from core.db.models import (
    AlertEvent,
    AlertRule,
    ApiKey,
    Article,
    ArticleAnalysis,
    ArticleBody,
    ArticleCore,
    ArticleVector,
    ArticleVersion,
    AuditLog,
    Base,
    CategoryType,
    CommunityVector,
    DailyBriefing,
    DailyBriefingItem,
    EmotionType,
    EntityVector,
    LLMCompareHourly,
    LLMFailureRecord,
    LLMUsageHourly,
    LLMUsageRaw,
    PendingSync,
    PersistStatus,
    PromptTemplate,
    RelationType,
    RelationTypeAlias,
    SentimentShift,
    SourceAuthority,
    SourceConfig,
    UnknownRelationType,
    VectorType,
)
from core.db.neo4j import Neo4jPool
from core.db.postgres import PostgresPool
from core.db.query_builders import (
    DatabaseType,
    DuckDBVectorQueryBuilder,
    EntitySimilarityQuery,
    PgVectorQueryBuilder,
    SimilarityQuery,
    VectorQueryBuilder,
    create_vector_query_builder,
)
from core.db.strategy import DatabaseStrategy, create_strategy
from core.protocols import GraphPool, RelationalPool

__all__ = [
    # Initializer
    "REQUIRED_NEO4J_CONSTRAINTS",
    "REQUIRED_TABLES",
    # Models
    "AlertEvent",
    "AlertRule",
    "ApiKey",
    "Article",
    "ArticleAnalysis",
    "ArticleBody",
    "ArticleCore",
    "ArticleVector",
    "ArticleVersion",
    "AuditLog",
    "Base",
    "CategoryType",
    "CommunityVector",
    "DailyBriefing",
    "DailyBriefingItem",
    "DatabaseInitError",
    # Strategy
    "DatabaseStrategy",
    # Query builders
    "DatabaseType",
    # Pools
    "DuckDBPool",
    "DuckDBVectorQueryBuilder",
    "EmotionType",
    "EntitySimilarityQuery",
    "EntityVector",
    "GraphDatabaseType",
    "GraphPool",
    "LLMCompareHourly",
    "LLMFailureRecord",
    "LLMUsageHourly",
    "LLMUsageRaw",
    "LadybugPool",
    "Neo4jPool",
    "PendingSync",
    "PersistStatus",
    "PgVectorQueryBuilder",
    "PostgresPool",
    "PromptTemplate",
    "RelationalPool",
    "SimilarityQuery",
    "SourceAuthority",
    "SourceConfig",
    "UnknownRelationType",
    "VectorType",
    "check_database_exists",
    "create_database",
    "create_strategy",
    "create_vector_query_builder",
    "initialize_database",
    "initialize_neo4j",
    "parse_dsn",
    "run_migrations",
    "verify_neo4j_constraints",
    "verify_tables",
    "wait_for_postgres",
]
