# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Storage module - Database repositories organized by database type.

PostgreSQL repositories: article_repo, vector_repo, pending_sync_repo, source_authority_repo
Neo4j repositories: Neo4jArticleRepo, Neo4jEntityRepo
"""

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
    # Neo4j
    "Neo4jArticleRepo",
    "Neo4jEntityRepo",
    "PendingSyncRepo",
    "SourceAuthorityRepo",
    "VectorRepo",
]
