# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add CHECK constraints and GIN indexes per design doc.

Revision ID: 14_add_check_constraints
Revises: 13_add_missing_columns
Create Date: 2026-06-11

Changes:
- articles_core: add CHECK constraint on document_type
- articles_core: add GIN index on doc_metadata
- sentiment_shifts: add CHECK constraint on shift_type
- daily_briefing_items: add CHECK constraint on rank (1-10)
- community_vectors: add GIN index on title
- sources: add CHECK constraint on interval_minutes (5-1440)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "14_add_check_constraints"
down_revision: str | None = "13_add_missing_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add CHECK constraints and GIN indexes."""
    # ── articles_core: document_type CHECK ──
    op.execute(
        "ALTER TABLE articles_core ADD CONSTRAINT chk_core_document_type "
        "CHECK (document_type IN ('news', 'social', 'official', 'research', 'opinion'))"
    )

    # ── articles_core: doc_metadata GIN index ──
    # CONCURRENTLY cannot run inside a transaction block; use autocommit_block.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_articles_doc_metadata_gin "
            "ON articles_core USING gin (doc_metadata)"
        )

    # ── sentiment_shifts: shift_type CHECK ──
    op.execute(
        "ALTER TABLE sentiment_shifts ADD CONSTRAINT chk_shift_type_values "
        "CHECK (shift_type IN ('abrupt', 'gradual'))"
    )

    # ── daily_briefing_items: rank CHECK (1-10) ──
    op.execute(
        "ALTER TABLE daily_briefing_items ADD CONSTRAINT chk_briefing_item_rank_range "
        "CHECK (rank >= 1 AND rank <= 10)"
    )

    # ── community_vectors: title GIN index ──
    # varchar columns need an explicit operator class for GIN; pg_trgm provides
    # gin_trgm_ops. CREATE EXTENSION can run inside a transaction.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_community_vectors_title_gin "
            "ON community_vectors USING gin (title gin_trgm_ops)"
        )

    # ── sources: interval_minutes CHECK (5-1440) ──
    op.execute(
        "ALTER TABLE sources ADD CONSTRAINT chk_sources_interval_minutes_range "
        "CHECK (interval_minutes >= 5 AND interval_minutes <= 1440)"
    )


def downgrade() -> None:
    """Remove CHECK constraints and GIN indexes."""
    # ── sources ──
    op.execute("ALTER TABLE sources DROP CONSTRAINT IF EXISTS chk_sources_interval_minutes_range")

    # ── community_vectors ──
    # DROP INDEX CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_community_vectors_title_gin")

    # ── daily_briefing_items ──
    op.execute(
        "ALTER TABLE daily_briefing_items DROP CONSTRAINT IF EXISTS chk_briefing_item_rank_range"
    )

    # ── sentiment_shifts ──
    op.execute("ALTER TABLE sentiment_shifts DROP CONSTRAINT IF EXISTS chk_shift_type_values")

    # ── articles_core ──
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_articles_doc_metadata_gin")
    op.execute("ALTER TABLE articles_core DROP CONSTRAINT IF EXISTS chk_core_document_type")
