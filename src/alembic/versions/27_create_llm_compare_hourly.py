# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Create llm_compare_hourly table for LLM shadow evaluation comparison.

Revision ID: 27_create_llm_compare_hourly
Revises: 26_add_other_category_enum
Create Date: 2026-07-17

Changes:
- Create llm_compare_hourly table (matches ORM LLMCompareHourly and DuckDB schema)
- Add unique constraint on (time_bucket, call_point, primary_model, candidate_model)
- Add 4 indexes for common query patterns

Background:
- ORM model LLMCompareHourly (src/core/db/models/llm.py:157) defined the table
- DuckDB schema (src/core/db/duckdb_schema.py:391) had it
- Repository src/modules/analytics/llm_compare/repo.py used it
- But NO Alembic migration created it in PostgreSQL → writes silently failed
- Discovered during API audit (llm_compare_hourly missing from PostgreSQL)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "27_create_llm_compare_hourly"
down_revision: str | None = "26_add_other_category_enum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create llm_compare_hourly table."""
    op.create_table(
        "llm_compare_hourly",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("time_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_point", sa.String(100), nullable=False),
        sa.Column("primary_model", sa.String(100), nullable=False),
        sa.Column("candidate_model", sa.String(100), nullable=False),
        sa.Column("comparison_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("primary_latency_sum", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column(
            "candidate_latency_sum", sa.Float(), nullable=False, server_default=sa.text("0.0")
        ),
        sa.Column(
            "primary_success_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "candidate_success_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "time_bucket",
            "call_point",
            "primary_model",
            "candidate_model",
            name="uq_llm_compare_hourly",
        ),
    )
    op.create_index("ix_llm_compare_hourly_time_bucket", "llm_compare_hourly", ["time_bucket"])
    op.create_index("ix_llm_compare_hourly_call_point", "llm_compare_hourly", ["call_point"])
    op.create_index("ix_llm_compare_hourly_primary", "llm_compare_hourly", ["primary_model"])
    op.create_index("ix_llm_compare_hourly_candidate", "llm_compare_hourly", ["candidate_model"])


def downgrade() -> None:
    """Drop llm_compare_hourly table."""
    op.drop_index("ix_llm_compare_hourly_candidate", table_name="llm_compare_hourly")
    op.drop_index("ix_llm_compare_hourly_primary", table_name="llm_compare_hourly")
    op.drop_index("ix_llm_compare_hourly_call_point", table_name="llm_compare_hourly")
    op.drop_index("ix_llm_compare_hourly_time_bucket", table_name="llm_compare_hourly")
    op.drop_table("llm_compare_hourly")
