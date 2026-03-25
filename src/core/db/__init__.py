# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core database module - PostgreSQL and Neo4j connection pools."""

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

__all__ = [
    "REQUIRED_NEO4J_CONSTRAINTS",
    "REQUIRED_TABLES",
    "Article",
    "ArticleVector",
    "Base",
    "CategoryType",
    "DatabaseInitError",
    "EmotionType",
    "EntityVector",
    "Neo4jPool",
    "PersistStatus",
    "PostgresPool",
    "SourceAuthority",
    "VectorType",
    "check_database_exists",
    "create_database",
    "initialize_database",
    "initialize_neo4j",
    "run_migrations",
    "verify_neo4j_constraints",
    "verify_tables",
]
