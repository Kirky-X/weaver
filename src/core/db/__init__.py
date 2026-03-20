# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core database module - PostgreSQL and Neo4j connection pools."""

from core.db.initializer import (
    check_database_exists,
    create_database,
    initialize_database,
    run_migrations,
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
    "Article",
    "ArticleVector",
    "Base",
    "CategoryType",
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
    "run_migrations",
    "verify_tables",
]
