# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB pending sync repository - reuses PostgreSQL implementation.

DuckDB supports SQLAlchemy ORM syntax, so we can directly reuse
the PostgreSQL PendingSyncRepo which uses pure ORM operations.
"""

from modules.storage.postgres.pending_sync_repo import PendingSyncRepo as DuckDBPendingSyncRepo

__all__ = ["DuckDBPendingSyncRepo"]
