# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Fix FK references from articles VIEW to articles_core table.

Revision ID: 19_fix_article_fk_references
Revises: 18_add_briefing_item_unique_constraints
Create Date: 2026-06-12

Changes:
- LLMFailureRecord.article_id: FK articles.id → articles_core.id (ondelete SET NULL)
- PendingSync.article_id: FK articles.id → articles_core.id (ondelete CASCADE)
- DailyBriefingItem.article_id: FK articles.id → articles_core.id (ondelete CASCADE)

The `articles` table was renamed to `articles_core` in migration 17,
but these three FK references were not updated. PostgreSQL VIEWs cannot
serve as FK targets, so new environments running migrations from scratch
would fail.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "19_fix_article_fk_references"
down_revision: str | None = "18_add_briefing_item_unique_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Fix FK references from articles to articles_core."""
    # LLMFailureRecord: drop old FK, add new FK pointing to articles_core
    op.drop_constraint(
        "llm_failure_records_article_id_fkey",
        "llm_failure_records",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "llm_failure_records_article_id_fkey",
        "llm_failure_records",
        "articles_core",
        ["article_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # PendingSync: drop old FK, add new FK pointing to articles_core
    op.drop_constraint(
        "pending_sync_article_id_fkey",
        "pending_sync",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "pending_sync_article_id_fkey",
        "pending_sync",
        "articles_core",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # DailyBriefingItem: drop old FK, add new FK pointing to articles_core
    op.drop_constraint(
        "daily_briefing_items_article_id_fkey",
        "daily_briefing_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_briefing_items_article_id_fkey",
        "daily_briefing_items",
        "articles_core",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Revert FK references back to articles (VIEW)."""
    # LLMFailureRecord: revert to articles
    op.drop_constraint(
        "llm_failure_records_article_id_fkey",
        "llm_failure_records",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "llm_failure_records_article_id_fkey",
        "llm_failure_records",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # PendingSync: revert to articles
    op.drop_constraint(
        "pending_sync_article_id_fkey",
        "pending_sync",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "pending_sync_article_id_fkey",
        "pending_sync",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # DailyBriefingItem: revert to articles
    op.drop_constraint(
        "daily_briefing_items_article_id_fkey",
        "daily_briefing_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "daily_briefing_items_article_id_fkey",
        "daily_briefing_items",
        "articles",
        ["article_id"],
        ["id"],
        ondelete="CASCADE",
    )
