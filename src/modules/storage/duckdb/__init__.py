# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""DuckDB storage module - reuses PostgreSQL ORM implementations.

DuckDB supports SQLAlchemy syntax, so we can reuse most repositories
from the postgres module. VectorRepo now uses the unified QueryBuilder
pattern for database-agnostic vector operations.
"""

from modules.storage.duckdb.article_repo import DuckDBArticleRepo
from modules.storage.duckdb.llm_usage_repo import DuckDBLLMUsageRepo
from modules.storage.duckdb.source_authority_repo import DuckDBSourceAuthorityRepo

__all__ = [
    "DuckDBArticleRepo",
    "DuckDBLLMUsageRepo",
    "DuckDBSourceAuthorityRepo",
]
