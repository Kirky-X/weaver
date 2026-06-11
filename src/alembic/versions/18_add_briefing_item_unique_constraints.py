# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Add UNIQUE constraints to daily_briefing_items.

Revision ID: 18_add_briefing_item_unique_constraints
Revises: 17_rename_tables
Create Date: 2026-06-11

Changes:
- Add UNIQUE(briefing_id, article_id) constraint to daily_briefing_items
- Add UNIQUE(briefing_id, rank) constraint to daily_briefing_items
"""

from collections.abc import Sequence

from alembic import op

revision: str = "18_add_briefing_item_unique_constraints"
down_revision: str | None = "17_rename_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add UNIQUE constraints to daily_briefing_items."""
    op.create_unique_constraint(
        "uq_briefing_item_article",
        "daily_briefing_items",
        ["briefing_id", "article_id"],
    )
    op.create_unique_constraint(
        "uq_briefing_item_rank",
        "daily_briefing_items",
        ["briefing_id", "rank"],
    )


def downgrade() -> None:
    """Drop UNIQUE constraints from daily_briefing_items."""
    op.drop_constraint(
        "uq_briefing_item_rank",
        "daily_briefing_items",
        type_="unique",
    )
    op.drop_constraint(
        "uq_briefing_item_article",
        "daily_briefing_items",
        type_="unique",
    )
