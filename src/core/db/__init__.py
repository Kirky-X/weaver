"""Core database module - PostgreSQL and Neo4j connection pools."""

from core.db.postgres import PostgresPool
from core.db.neo4j import Neo4jPool
from core.db.initializer import (
    initialize_database,
    check_database_exists,
    create_database,
    verify_tables,
    run_migrations,
)
from core.db.models import (
    Base,
    Article,
    ArticleVector,
    EntityVector,
    SourceAuthority,
    ArticleEntity,
    CategoryType,
    PersistStatus,
    EmotionType,
    VectorType,
)

__all__ = [
    "PostgresPool",
    "Neo4jPool",
    "initialize_database",
    "check_database_exists",
    "create_database",
    "verify_tables",
    "run_migrations",
    "Base",
    "Article",
    "ArticleVector",
    "EntityVector",
    "SourceAuthority",
    "ArticleEntity",
    "CategoryType",
    "PersistStatus",
    "EmotionType",
    "VectorType",
]
