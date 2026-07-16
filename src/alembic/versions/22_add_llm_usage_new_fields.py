# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add cached_tokens, reasoning_tokens, cost_usd to llm_usage tables.

Revision ID: 22_add_llm_usage_new_fields
Revises: 21_extract_article_processing
Create Date: 2026-06-18

Changes:
- Add cached_tokens, reasoning_tokens, cost_usd columns to llm_usage_raw
- Add cached_tokens_sum, reasoning_tokens_sum, cost_usd_sum columns to llm_usage_hourly
- Create composite index ix_llm_usage_raw_label_callpoint_created on llm_usage_raw
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "22_add_llm_usage_new_fields"
down_revision: str | None = "21_extract_article_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add new columns and composite index for LLM usage tracking."""
    # 1. Add columns to llm_usage_raw
    op.add_column(
        "llm_usage_raw",
        sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "llm_usage_raw",
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "llm_usage_raw",
        sa.Column("cost_usd", sa.Numeric(12, 8), nullable=False, server_default=sa.text("0.0")),
    )

    # 2. Add columns to llm_usage_hourly
    op.add_column(
        "llm_usage_hourly",
        sa.Column("cached_tokens_sum", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "llm_usage_hourly",
        sa.Column(
            "reasoning_tokens_sum", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "llm_usage_hourly",
        sa.Column("cost_usd_sum", sa.Numeric(14, 8), nullable=False, server_default=sa.text("0.0")),
    )

    # 3. Create composite index on llm_usage_raw
    op.create_index(
        "ix_llm_usage_raw_label_callpoint_created",
        "llm_usage_raw",
        ["label", "call_point", "created_at"],
    )


def downgrade() -> None:
    """Remove new columns and composite index."""
    # 1. Drop composite index
    op.drop_index("ix_llm_usage_raw_label_callpoint_created", table_name="llm_usage_raw")

    # 2. Drop columns from llm_usage_hourly
    op.drop_column("llm_usage_hourly", "cost_usd_sum")
    op.drop_column("llm_usage_hourly", "reasoning_tokens_sum")
    op.drop_column("llm_usage_hourly", "cached_tokens_sum")

    # 3. Drop columns from llm_usage_raw
    op.drop_column("llm_usage_raw", "cost_usd")
    op.drop_column("llm_usage_raw", "reasoning_tokens")
    op.drop_column("llm_usage_raw", "cached_tokens")
