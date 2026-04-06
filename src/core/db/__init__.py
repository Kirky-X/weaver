# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core database module - PostgreSQL, Neo4j, DuckDB, and LadybugDB connection pools."""

from core.db.duckdb_pool import DuckDBPool
from core.db.initializer import (
    REQUIRED_NEO4J_CONSTRAINTS,
    REQUIRED_TABLES,
    DatabaseInitError,
    check_database_exists,
    create_database,
    initialize_database,
    initialize_neo4j,
    run_migrations,
    verify_neo4j_constraints,
    verify_tables,
)
from core.db.ladybug_pool import LadybugPool
from core.db.models import (
    Article,
    ArticleVector,
    Base,
    CategoryType,
    EmotionType,
    EntityVector,
    PersistStatus,
    SourceAuthority,
    VectorType,
)
from core.db.neo4j import Neo4jPool
from core.db.postgres import PostgresPool
from core.db.strategy import DatabaseStrategy, create_strategy
from core.protocols import GraphPool, RelationalPool

__all__ = [
    "REQUIRED_NEO4J_CONSTRAINTS",
    "REQUIRED_TABLES",
    "Article",
    "ArticleVector",
    "Base",
    "CategoryType",
    "DatabaseInitError",
    "DatabaseStrategy",
    "DuckDBPool",
    "EmotionType",
    "EntityVector",
    "GraphPool",
    "LadybugPool",
    "Neo4jPool",
    "PersistStatus",
    "PostgresPool",
    "RelationalPool",
    "SourceAuthority",
    "VectorType",
    "check_database_exists",
    "create_database",
    "create_strategy",
    "initialize_database",
    "initialize_neo4j",
    "run_migrations",
    "verify_neo4j_constraints",
    "verify_tables",
]
