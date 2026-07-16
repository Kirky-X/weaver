# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""DuckDB source authority repository - reuses PostgreSQL implementation.

DuckDB supports SQLAlchemy ORM syntax, so we can directly reuse
the PostgreSQL SourceAuthorityRepo which uses pure ORM operations.
"""

from modules.storage.postgres.source_authority_repo import (
    SourceAuthorityRepo as DuckDBSourceAuthorityRepo,
)

__all__ = ["DuckDBSourceAuthorityRepo"]
