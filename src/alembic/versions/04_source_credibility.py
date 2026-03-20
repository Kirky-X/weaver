# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Add credibility and tier columns to sources table

Revision ID: 04_source_credibility
Revises: 03_remove_article_entities
Create Date: 2026-03-21

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "04_source_credibility"
down_revision: Union[str, None] = "03_remove_article_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create sources table
    op.create_table(
        "sources",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="rss"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("per_host_concurrency", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("credibility", sa.Numeric(3, 2), nullable=True),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("last_crawl_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.String(200), nullable=True),
        sa.Column("last_modified", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "credibility >= 0 AND credibility <= 1",
            name="chk_sources_credibility_range",
        ),
        sa.CheckConstraint(
            "tier >= 1 AND tier <= 3",
            name="chk_sources_tier_range",
        ),
    )

    op.create_index("idx_sources_host", "sources", [sa.text("url")])
    op.create_index("idx_sources_enabled", "sources", ["enabled"])


def downgrade() -> None:
    op.drop_index("idx_sources_enabled", table_name="sources")
    op.drop_index("idx_sources_host", table_name="sources")
    op.drop_table("sources")
