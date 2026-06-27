# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Storage module - Database repositories organized by database type.

PostgreSQL repositories: article_repo, vector_repo, pending_sync_repo, source_authority_repo
Neo4j repositories: Neo4jArticleRepo, Neo4jEntityRepo
DuckDB repositories: llm_usage_repo
LadybugDB repositories: article_repo, entity_repo
"""

from modules.storage.base_entity_repo import BaseEntityRepo

# DuckDB repositories
from modules.storage.duckdb.llm_usage_repo import DuckDBLLMUsageRepo
from modules.storage.graph_repo import GraphRepository

# LadybugDB repositories
from modules.storage.ladybug.article_repo import LadybugArticleRepo
from modules.storage.ladybug.entity_repo import LadybugEntityRepo

# Neo4j repositories
from modules.storage.neo4j import Neo4jArticleRepo, Neo4jEntityRepo

# PostgreSQL repositories
from modules.storage.postgres.article_repo import ArticleRepo
from modules.storage.postgres.pending_sync_repo import PendingSyncRepo
from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo
from modules.storage.postgres.vector_repo import VectorRepo

__all__ = [
    # PostgreSQL
    "ArticleRepo",
    # Base
    "BaseEntityRepo",
    # DuckDB
    "DuckDBLLMUsageRepo",
    # Graph
    "GraphRepository",
    # LadybugDB
    "LadybugArticleRepo",
    "LadybugEntityRepo",
    # Neo4j
    "Neo4jArticleRepo",
    "Neo4jEntityRepo",
    "PendingSyncRepo",
    "SourceAuthorityRepo",
    "VectorRepo",
]
