# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Create article_versions table.

Revision ID: 09_create_article_versions_table
Revises: 08_create_alert_tables
Create Date: 2026-06-10

Changes per Weaver-数据库设计文档 §9.11.6:
- Create article_versions table with FK to articles_core
- UNIQUE(article_id, version) constraint
- Index on (article_id, version DESC)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "09_create_article_versions_table"
down_revision: str | None = "08_create_alert_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create article_versions table."""
    op.create_table(
        "article_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles_core.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(20), nullable=True),
        sa.Column("score", sa.Numeric(3, 2), nullable=True),
        sa.Column("changed_fields", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("article_id", "version", name="uq_article_version"),
    )
    op.create_index(
        "idx_article_versions_id",
        "article_versions",
        ["article_id", sa.text("version DESC")],
    )


def downgrade() -> None:
    """Drop article_versions table."""
    op.drop_index("idx_article_versions_id", table_name="article_versions")
    op.drop_table("article_versions")
