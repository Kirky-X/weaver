# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Create saga_logs table for Saga compensation transaction logging.

Revision ID: 20_create_saga_logs
Revises: 17_rename_tables
Create Date: 2026-06-12

Changes:
- Create saga_logs table for Saga execution log storage
- Add indexes on saga_id, article_id, step_status for query performance
- Extend persist_status enum with Saga-related states
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20_create_saga_logs"
down_revision: str | None = "17_rename_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create saga_logs table and extend persist_status enum."""
    # Step 1: Extend persist_status enum with Saga states
    op.execute("""
        ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_started' BEFORE 'failed';
    """)
    op.execute("""
        ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_pg_writing' BEFORE 'failed';
    """)
    op.execute("""
        ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_neo4j_writing' BEFORE 'failed';
    """)
    op.execute("""
        ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_compensating' BEFORE 'failed';
    """)
    op.execute("""
        ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_compensated' BEFORE 'failed';
    """)
    op.execute("""
        ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_completed' BEFORE 'failed';
    """)

    # Step 2: Create saga_logs table
    op.create_table(
        "saga_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("saga_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_name", sa.String(50), nullable=False),
        sa.Column("step_status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compensation_data", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Step 3: Create indexes
    op.create_index("idx_saga_logs_saga_id", "saga_logs", ["saga_id"])
    op.create_index("idx_saga_logs_article_id", "saga_logs", ["article_id"])
    op.create_index("idx_saga_logs_step_status", "saga_logs", ["step_status"])


def downgrade() -> None:
    """Drop saga_logs table and remove Saga states from persist_status enum."""
    # Drop indexes and table
    op.drop_index("idx_saga_logs_step_status", table_name="saga_logs")
    op.drop_index("idx_saga_logs_article_id", table_name="saga_logs")
    op.drop_index("idx_saga_logs_saga_id", table_name="saga_logs")
    op.drop_table("saga_logs")

    # Note: PostgreSQL does not support removing enum values easily.
    # A full downgrade would require recreating the enum type without Saga states.
    # This is acceptable as downgrades are primarily for development.
