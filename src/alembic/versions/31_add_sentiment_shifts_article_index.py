# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add covering index for article-level sentiment_shifts queries.

Revision ID: 31_add_sentiment_shifts_article_index
Revises: 30_extend_sentiment_shifts_for_article_tracking
Create Date: 2026-07-17

Background:
- T003 SentimentTrackerNode queries the most recent article-level shift for
  a given entity via:
      SELECT ... FROM sentiment_shifts
      WHERE entity_name = :entity AND article_id IS NOT NULL
      ORDER BY detected_at DESC LIMIT 1
- Without an index covering (entity_name, article_id, detected_at), every
  article processed triggers a full scan on sentiment_shifts.
- Performance review HIGH-1 (T003-sub4): add a partial composite index to
  cover the article-level lookup path.
- Partial index (WHERE article_id IS NOT NULL) keeps the index small: only
  article-level rows (T003) are indexed, community-level rows (existing
  SentimentShiftDetector) are excluded.
- DuckDB does not support partial indexes; the DuckDB schema upgrade path
  creates a regular composite index instead (see duckdb_schema.py).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "31_add_sentiment_shifts_article_index"
down_revision: str | None = "30_extend_sentiment_shifts_for_article_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add partial composite index for article-level shift lookup."""
    op.create_index(
        "idx_shifts_entity_article_detected",
        "sentiment_shifts",
        ["entity_name", "article_id", "detected_at"],
        unique=False,
        postgresql_where="article_id IS NOT NULL",
    )


def downgrade() -> None:
    """Drop the article-level shift lookup index."""
    op.drop_index(
        "idx_shifts_entity_article_detected",
        table_name="sentiment_shifts",
    )
