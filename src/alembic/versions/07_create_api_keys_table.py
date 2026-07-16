# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Create api_keys table.

Revision ID: 07_create_api_keys_table
Revises: 06_vertical_split_articles
Create Date: 2026-06-10

Changes per Weaver-数据库设计文档 §1.6.3:
- Create api_keys table with bcrypt hash storage
- Partial index on expires_at WHERE is_revoked = false
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "07_create_api_keys_table"
down_revision: str | None = "06_vertical_split_articles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create api_keys table."""
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.String(64), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(256), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[\"search:read\"]'::jsonb"),
        ),
        sa.Column(
            "rate_limit_per_min",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_api_keys_key_id", "api_keys", ["key_id"])
    op.create_index(
        "idx_api_keys_expires",
        "api_keys",
        ["expires_at"],
        postgresql_where=sa.text("is_revoked = false"),
    )


def downgrade() -> None:
    """Drop api_keys table."""
    op.drop_index("idx_api_keys_expires", table_name="api_keys")
    op.drop_index("idx_api_keys_key_id", table_name="api_keys")
    op.drop_table("api_keys")
