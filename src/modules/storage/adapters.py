# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

"""Unified storage adapters - Re-exports all storage interfaces and implementations."""

# Base protocols
from core.protocols import (
    ArticleRepository,
    EntityRepository,
    VectorRepository,
)

# Database-specific repos
from modules.storage.duckdb import (
    DuckDBArticleRepo,
    DuckDBLLMUsageRepo,
    DuckDBSourceAuthorityRepo,
)
from modules.storage.graph_repo import GraphRepository
from modules.storage.neo4j import Neo4jArticleRepo, Neo4jEntityRepo
from modules.storage.postgres.article_repo import ArticleRepo
from modules.storage.postgres.pending_sync_repo import PendingSyncRepo
from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo
from modules.storage.postgres.vector_repo import VectorRepo

__all__ = [
    "ArticleRepo",
    "ArticleRepository",
    "DuckDBArticleRepo",
    "DuckDBLLMUsageRepo",
    "DuckDBSourceAuthorityRepo",
    "EntityRepository",
    "GraphRepository",
    "Neo4jArticleRepo",
    "Neo4jEntityRepo",
    "PendingSyncRepo",
    "SourceAuthorityRepo",
    "VectorRepo",
    "VectorRepository",
]
