# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Add pending_sync table for tracking pending Neo4j sync operations

Revision ID: 05_pending_sync
Revises: 04_source_credibility
Create Date: 2026-03-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "05_pending_sync"
down_revision: str | None = "04_source_credibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_sync",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sync_type", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index("idx_pending_sync_article_id", "pending_sync", ["article_id"])
    op.create_index("idx_pending_sync_status", "pending_sync", ["status"])
    op.create_index("idx_pending_sync_created_at", "pending_sync", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_pending_sync_created_at", table_name="pending_sync")
    op.drop_index("idx_pending_sync_status", table_name="pending_sync")
    op.drop_index("idx_pending_sync_article_id", table_name="pending_sync")
    op.drop_table("pending_sync")
