# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Create analytics tables: sentiment_shifts, daily_briefings, daily_briefing_items.

Revision ID: 04_create_analytics_tables
Revises: 03_extend_articles_fields
Create Date: 2026-06-09

Changes:
- Create sentiment_shifts table for community sentiment tracking
- Create daily_briefings table for daily digest generation
- Create daily_briefing_items table for briefing article references
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "04_create_analytics_tables"
down_revision: str | None = "03_extend_articles_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create analytics tables for sentiment tracking and daily briefings."""
    # === SENTIMENT_SHIFTS ===
    op.create_table(
        "sentiment_shifts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("community_id", sa.String(100), nullable=False),
        sa.Column("shift_type", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("magnitude", sa.Numeric(5, 4), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_avg", sa.Numeric(5, 4), nullable=True),
        sa.Column("after_avg", sa.Numeric(5, 4), nullable=True),
        sa.Column("trigger_article_ids", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_shifts_community", "sentiment_shifts", ["community_id"])
    op.create_index("idx_shifts_type", "sentiment_shifts", ["shift_type"])
    op.create_index("idx_shifts_detected", "sentiment_shifts", ["detected_at"])

    # === DAILY_BRIEFINGS ===
    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("briefing_date", sa.DateTime(timezone=True), nullable=False, unique=True),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_briefings_date", "daily_briefings", ["briefing_date"])

    # === DAILY_BRIEFING_ITEMS ===
    op.create_table(
        "daily_briefing_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "briefing_id",
            sa.BigInteger(),
            sa.ForeignKey("daily_briefings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Drop analytics tables."""
    op.drop_table("daily_briefing_items")
    op.drop_index("idx_briefings_date", table_name="daily_briefings")
    op.drop_table("daily_briefings")
    op.drop_index("idx_shifts_detected", table_name="sentiment_shifts")
    op.drop_index("idx_shifts_type", table_name="sentiment_shifts")
    op.drop_index("idx_shifts_community", table_name="sentiment_shifts")
    op.drop_table("sentiment_shifts")
