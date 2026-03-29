# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Add llm_usage_raw and llm_usage_hourly tables for LLM usage tracking

Revision ID: 06_llm_usage
Revises: f23755e6c748
Create Date: 2026-03-29

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "06_llm_usage"
down_revision: Union[str, None] = "f23755e6c748"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create llm_usage_raw table for individual LLM call records
    op.create_table(
        "llm_usage_raw",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("call_point", sa.String(100), nullable=False),
        sa.Column("llm_type", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("article_id", sa.BigInteger(), nullable=True),
        sa.Column("task_id", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index("ix_llm_usage_raw_created_at", "llm_usage_raw", ["created_at"])
    op.create_index("ix_llm_usage_raw_label", "llm_usage_raw", ["label"])

    # Create llm_usage_hourly table for aggregated statistics
    op.create_table(
        "llm_usage_hourly",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("time_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("call_point", sa.String(100), nullable=False),
        sa.Column("llm_type", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_avg_ms", sa.Float(), nullable=False),
        sa.Column("latency_min_ms", sa.Float(), nullable=False),
        sa.Column("latency_max_ms", sa.Float(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Unique constraint for idempotent upsert
    op.create_unique_constraint(
        "uq_llm_usage_hourly",
        "llm_usage_hourly",
        ["time_bucket", "label", "call_point"],
    )
    op.create_index("ix_llm_usage_hourly_time_bucket", "llm_usage_hourly", ["time_bucket"])
    op.create_index("ix_llm_usage_hourly_provider", "llm_usage_hourly", ["provider"])
    op.create_index("ix_llm_usage_hourly_model", "llm_usage_hourly", ["model"])


def downgrade() -> None:
    # Drop llm_usage_hourly
    op.drop_index("ix_llm_usage_hourly_model", table_name="llm_usage_hourly")
    op.drop_index("ix_llm_usage_hourly_provider", table_name="llm_usage_hourly")
    op.drop_index("ix_llm_usage_hourly_time_bucket", table_name="llm_usage_hourly")
    op.drop_constraint("uq_llm_usage_hourly", "llm_usage_hourly")
    op.drop_table("llm_usage_hourly")

    # Drop llm_usage_raw
    op.drop_index("ix_llm_usage_raw_label", table_name="llm_usage_raw")
    op.drop_index("ix_llm_usage_raw_created_at", table_name="llm_usage_raw")
    op.drop_table("llm_usage_raw")
