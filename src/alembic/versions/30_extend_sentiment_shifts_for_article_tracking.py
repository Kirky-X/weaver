# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Extend sentiment_shifts table for article-level tracking.

Revision ID: 30_extend_sentiment_shifts_for_article_tracking
Revises: 29_seed_default_alert_rules
Create Date: 2026-07-17

Changes:
- sentiment_shifts: add article_id (UUID, nullable)
- sentiment_shifts: add entity_name (VARCHAR(200), nullable)
- sentiment_shifts: add shift_value (NUMERIC(5,4), nullable)

Background:
- Existing sentiment_shifts table tracks community-level sentiment shifts
  detected by SentimentShiftDetector (PELT + CUSUM algorithm, scheduled task).
- T003 SentimentTrackerNode adds article-level sentiment tracking: when a
  new article is processed, compare its sentiment_score with the previous
  article mentioning the same entity, and record the shift.
- New fields are nullable to preserve backward compatibility with existing
  community-level records. Article-level records reuse existing fields:
    community_id = entity_name (used as identifier)
    shift_type = 'mean_shift' (single-article comparison)
    direction = 'up'/'down'/'stable'
    magnitude = abs(shift_value)
    confidence = 1.0 (article-level, high confidence)
    detected_at = window_start = window_end = article.publish_time
    before_avg = previous article sentiment_score
    after_avg = current article sentiment_score
  New fields:
    article_id = current article UUID
    entity_name = entity being tracked
    shift_value = after_avg - before_avg (signed, not absolute)

Downgrade safety:
- Downgrade simply drops the 3 columns. No data migration needed because
  article-level records (identified by article_id IS NOT NULL) lose their
  article-specific metadata but the community-level fields remain valid.
- Per Rule 12, no row count to print (DDL-only operation, no DELETE).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "30_extend_sentiment_shifts_for_article_tracking"
down_revision: str | None = "29_seed_default_alert_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add article_id, entity_name, shift_value to sentiment_shifts."""
    op.add_column(
        "sentiment_shifts",
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sentiment_shifts",
        sa.Column("entity_name", sa.String(200), nullable=True),
    )
    op.add_column(
        "sentiment_shifts",
        sa.Column("shift_value", sa.Numeric(5, 4), nullable=True),
    )


def downgrade() -> None:
    """Remove article_id, entity_name, shift_value from sentiment_shifts."""
    op.drop_column("sentiment_shifts", "shift_value")
    op.drop_column("sentiment_shifts", "entity_name")
    op.drop_column("sentiment_shifts", "article_id")
