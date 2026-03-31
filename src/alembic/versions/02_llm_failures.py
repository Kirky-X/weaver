# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Add llm_failures table for persistent LLM failure logging

Revision ID: 02_llm_failures
Revises: 01_initial
Create Date: 2026-03-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "02_llm_failures"
down_revision: str | None = "01_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_failures",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("call_point", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "latency_ms",
            postgresql.NUMERIC(precision=10, scale=2),
            nullable=True,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_tried", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index("idx_llm_failures_created", "llm_failures", ["created_at"])
    op.create_index("idx_llm_failures_article", "llm_failures", ["article_id"])
    op.create_index("idx_llm_failures_call_point", "llm_failures", ["call_point"])
    op.create_index("idx_llm_failures_provider", "llm_failures", ["provider"])


def downgrade() -> None:
    op.drop_index("idx_llm_failures_provider", table_name="llm_failures")
    op.drop_index("idx_llm_failures_call_point", table_name="llm_failures")
    op.drop_index("idx_llm_failures_article", table_name="llm_failures")
    op.drop_index("idx_llm_failures_created", table_name="llm_failures")
    op.drop_table("llm_failures")
