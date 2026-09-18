# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add missing columns.

Revision ID: 13_add_missing_columns
Revises: 12_add_optimization_indexes
Create Date: 2026-06-11

Changes:
- community_vectors: add title, summary, entity_count, article_count, rank
- daily_briefings: add title, summary, status; change briefing_date to DATE
- daily_briefing_items: add score, score_breakdown
- sentiment_shifts: add community_title, window_start, window_end
- source_authorities: add manual_score, final_score, article_count, last_crawled_at
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "13_add_missing_columns"
down_revision: str | None = "12_add_optimization_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add missing columns to align with design document specifications."""
    # ── community_vectors ──
    op.add_column("community_vectors", sa.Column("title", sa.String(200), nullable=True))
    op.add_column("community_vectors", sa.Column("summary", sa.Text, nullable=True))
    op.add_column(
        "community_vectors",
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "community_vectors",
        sa.Column("article_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("community_vectors", sa.Column("rank", sa.Numeric(3, 2), nullable=True))

    # ── daily_briefings ──
    op.add_column("daily_briefings", sa.Column("title", sa.String(200), nullable=True))
    op.add_column("daily_briefings", sa.Column("summary", sa.Text, nullable=True))
    op.add_column(
        "daily_briefings",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="'draft'",
        ),
    )
    op.create_check_constraint(
        "chk_briefing_status",
        "daily_briefings",
        "status IN ('draft', 'published', 'archived')",
    )
    # Change briefing_date from TIMESTAMPTZ to DATE.
    # collapsing TIMESTAMPTZ→DATE can fold multiple timestamps that
    # share a calendar date into the same DATE value, violating the single
    # column UNIQUE on briefing_date (still in force until migration 32).
    # Deduplicate first, keeping the newest row per folded date (its
    # briefing_items cascade along; earlier partial rows are dropped).
    folded = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "SELECT briefing_date::date AS d FROM daily_briefings "
                "GROUP BY briefing_date::date HAVING count(*) > 1) dup"
            ),
        )
        .scalar()
    )
    if folded:
        print(
            f"WARNING 13_add_missing_columns.upgrade: {folded} date(s) have multiple "
            "daily_briefings rows that would collide when briefing_date is folded "
            "to DATE; keeping the newest row per date and deleting the rest."
        )
        op.execute("""
            DELETE FROM daily_briefings a
            USING daily_briefings b
            WHERE a.briefing_date::date = b.briefing_date::date
              AND a.generated_at < b.generated_at
        """)
    op.alter_column(
        "daily_briefings",
        "briefing_date",
        type_=sa.Date(),
        existing_type=sa.DateTime(timezone=True),
        postgresql_using="briefing_date::date",
    )

    # ── daily_briefing_items ──
    op.add_column(
        "daily_briefing_items",
        sa.Column("score", sa.Numeric(5, 3), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_briefing_items",
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=True),
    )

    # ── sentiment_shifts ──
    op.add_column("sentiment_shifts", sa.Column("community_title", sa.String(200), nullable=True))
    op.add_column(
        "sentiment_shifts",
        sa.Column(
            "window_start",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.add_column(
        "sentiment_shifts",
        sa.Column(
            "window_end",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── source_authorities ──
    op.add_column("source_authorities", sa.Column("manual_score", sa.Numeric(3, 2), nullable=True))
    op.add_column("source_authorities", sa.Column("final_score", sa.Numeric(3, 2), nullable=True))
    op.add_column(
        "source_authorities",
        sa.Column("article_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "source_authorities",
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove added columns."""
    # ── source_authorities ──
    op.drop_column("source_authorities", "last_crawled_at")
    op.drop_column("source_authorities", "article_count")
    op.drop_column("source_authorities", "final_score")
    op.drop_column("source_authorities", "manual_score")

    # ── sentiment_shifts ──
    op.drop_column("sentiment_shifts", "window_end")
    op.drop_column("sentiment_shifts", "window_start")
    op.drop_column("sentiment_shifts", "community_title")

    # ── daily_briefing_items ──
    op.drop_column("daily_briefing_items", "score_breakdown")
    op.drop_column("daily_briefing_items", "score")

    # ── daily_briefings ──
    # DATE→TIMESTAMPTZ via bare cast is timezone-dependent (uses the
    # server's TimeZone GUC); pin the conversion to UTC for determinism.
    op.alter_column(
        "daily_briefings",
        "briefing_date",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.Date(),
        postgresql_using="briefing_date::timestamp AT TIME ZONE 'UTC'",
    )
    op.drop_constraint("chk_briefing_status", "daily_briefings", type_="check")
    op.drop_column("daily_briefings", "status")
    op.drop_column("daily_briefings", "summary")
    op.drop_column("daily_briefings", "title")

    # ── community_vectors ──
    op.drop_column("community_vectors", "rank")
    op.drop_column("community_vectors", "article_count")
    op.drop_column("community_vectors", "entity_count")
    op.drop_column("community_vectors", "summary")
    op.drop_column("community_vectors", "title")
