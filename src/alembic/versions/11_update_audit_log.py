# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Update audit_log table to match design doc §12.3.

Revision ID: 11_update_audit_log
Revises: 10_simplify_prompt_templates
Create Date: 2026-06-10

Changes per Weaver-数据库设计文档 §12.3:
- Add user_agent TEXT column
- Change key_id VARCHAR(100) → VARCHAR(64)
- Change action VARCHAR(50) → VARCHAR(64)
- Change target_type VARCHAR(50) → VARCHAR(32)
- Change target_id VARCHAR(100) → TEXT
- Recreate idx_audit_key as composite (key_id, created_at DESC)
- Recreate idx_audit_occurred as (created_at DESC)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "11_update_audit_log"
down_revision: str | None = "10_simplify_prompt_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update audit_log schema to match design doc."""
    # Add user_agent column
    op.add_column("audit_log", sa.Column("user_agent", sa.Text(), nullable=True))

    # Alter column types
    op.alter_column("audit_log", "key_id", type_=sa.String(64), nullable=False)
    op.alter_column("audit_log", "action", type_=sa.String(64), nullable=False)
    op.alter_column("audit_log", "target_type", type_=sa.String(32), nullable=True)
    op.alter_column("audit_log", "target_id", type_=sa.Text(), nullable=True)

    # Recreate indexes to match design doc
    op.drop_index("idx_audit_key", table_name="audit_log")
    op.drop_index("idx_audit_occurred", table_name="audit_log")
    op.create_index("idx_audit_occurred", "audit_log", [sa.text("created_at DESC")])
    op.create_index("idx_audit_key", "audit_log", ["key_id", sa.text("created_at DESC")])


def downgrade() -> None:
    """Revert audit_log schema changes."""
    op.drop_index("idx_audit_key", table_name="audit_log")
    op.drop_index("idx_audit_occurred", table_name="audit_log")
    op.create_index("idx_audit_key", "audit_log", ["key_id"])
    op.create_index("idx_audit_occurred", "audit_log", ["created_at"])

    op.alter_column("audit_log", "target_id", type_=sa.String(100), nullable=True)
    op.alter_column("audit_log", "target_type", type_=sa.String(50), nullable=True)
    op.alter_column("audit_log", "action", type_=sa.String(50), nullable=False)
    op.alter_column("audit_log", "key_id", type_=sa.String(100), nullable=False)
    op.drop_column("audit_log", "user_agent")
