# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add title index to articles_core for DB-level dedup (Stage 3 safety net).

Revision ID: 34_add_articles_core_title_index
Revises: 33_add_alert_events_payload_hash
Create Date: 2026-07-23

Changes:
- articles_core: add idx_articles_core_title on (title)
  Accelerates ArticleRepository.get_existing_titles(titles) which runs
  `SELECT title FROM articles_core WHERE title IN (...)` as a Stage 3
  safety-net dedup when SimHash fingerprints are missing (Redis
  degradation, process restart, scheduler timing).

Background:
- Stage 1 (URL dedup) and Stage 2 (SimHash title dedup) have no DB-level
  fallback. When SimHash fingerprints are lost, identical titles across
  batches slip into the database (observed: 7 duplicate title groups from
  a seed_sources.py fast-phase run).
- get_existing_titles performs exact-match title lookup. Without an index
  on title, every call triggers a sequential scan on articles_core.

Cross-database compatibility:
- PostgreSQL: CREATE INDEX CONCURRENTLY (non-blocking, autocommit).
- DuckDB: CREATE INDEX IF NOT EXISTS (added in duckdb_schema.py).
- The existing idx_articles_url_lookup is a covering index on
  (source_url) INCLUDE (id, title, publish_time) — it does NOT support
  WHERE title IN (...) lookups, hence the need for a dedicated title index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "34_add_articles_core_title_index"
down_revision: str | None = "33_add_alert_events_payload_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add title index to articles_core."""
    # CONCURRENTLY cannot run inside a transaction block; use autocommit_block.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_core_title "
            "ON articles_core (title)"
        )


def downgrade() -> None:
    """Drop the title index."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_core_title")
