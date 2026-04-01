# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Storage module - Database repositories and storage backends.

This module provides:
- postgres: PostgreSQL repositories
- neo4j: Neo4j graph repositories
- redis: Redis storage (future)

For LLM usage statistics, use modules.analytics instead.
"""

# Backward compatibility - re-export from analytics module
# These will be deprecated in a future version
from modules.analytics.llm_failure import LLMFailureRepo
from modules.analytics.llm_usage import LLMUsageRepo

# Neo4j repositories
from modules.storage.neo4j import Neo4jArticleRepo, Neo4jEntityRepo

# PostgreSQL repositories
from modules.storage.postgres import (
    ArticleRepo,
    PendingSyncRepo,
    SourceAuthorityRepo,
    VectorRepo,
)

__all__ = [
    "ArticleRepo",
    "LLMFailureRepo",
    "LLMUsageRepo",
    "Neo4jArticleRepo",
    "Neo4jEntityRepo",
    "PendingSyncRepo",
    "SourceAuthorityRepo",
    "VectorRepo",
]
