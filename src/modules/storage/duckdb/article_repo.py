# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""DuckDB article repository - reuses PostgreSQL implementation.

DuckDB supports SQLAlchemy ORM syntax, so we can directly reuse
the PostgreSQL ArticleRepo which uses pure ORM operations.
"""

from modules.storage.postgres.article_repo import ArticleRepo as DuckDBArticleRepo

__all__ = ["DuckDBArticleRepo"]
