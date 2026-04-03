# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB source authority repository - reuses PostgreSQL implementation.

DuckDB supports SQLAlchemy ORM syntax, so we can directly reuse
the PostgreSQL SourceAuthorityRepo which uses pure ORM operations.
"""

from modules.storage.postgres.source_authority_repo import (
    SourceAuthorityRepo as DuckDBSourceAuthorityRepo,
)

__all__ = ["DuckDBSourceAuthorityRepo"]
