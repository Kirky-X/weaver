# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB article repository - reuses PostgreSQL implementation.

DuckDB supports SQLAlchemy ORM syntax, so we can directly reuse
the PostgreSQL ArticleRepo which uses pure ORM operations.
"""

from modules.storage.postgres.article_repo import ArticleRepo as DuckDBArticleRepo

__all__ = ["DuckDBArticleRepo"]
