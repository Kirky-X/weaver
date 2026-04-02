# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB storage module - reuses PostgreSQL ORM implementations.

DuckDB supports SQLAlchemy syntax, so we can reuse most repositories
from the postgres module. Only VectorRepo needs adaptation for
DuckDB's array_cosine_similarity() function.
"""

from modules.storage.duckdb.article_repo import DuckDBArticleRepo
from modules.storage.duckdb.pending_sync_repo import DuckDBPendingSyncRepo
from modules.storage.duckdb.source_authority_repo import DuckDBSourceAuthorityRepo
from modules.storage.duckdb.vector_repo import DuckDBVectorRepo

__all__ = [
    "DuckDBArticleRepo",
    "DuckDBPendingSyncRepo",
    "DuckDBSourceAuthorityRepo",
    "DuckDBVectorRepo",
]
