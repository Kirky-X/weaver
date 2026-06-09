# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Simplify prompt_templates to match ORM model.

Revision ID: 10_simplify_prompt_templates
Revises: 09_create_article_versions_table
Create Date: 2026-06-10

Changes:
- Drop unused columns: version, prompt_type, is_active, change_reason,
  prompt_metadata, created_by
- Rename content → template
- Change unique constraint from (name, version) to just (name)
- Drop obsolete indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10_simplify_prompt_templates"
down_revision: str | None = "09_create_article_versions_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Simplify prompt_templates schema."""
    # Drop old constraints and indexes
    op.drop_constraint("uq_prompt_name_version", "prompt_templates")
    op.drop_index("idx_prompt_templates_name", table_name="prompt_templates")
    op.drop_index("idx_prompt_templates_created_at", table_name="prompt_templates")

    # Rename content → template
    op.alter_column("prompt_templates", "content", new_column_name="template")

    # Drop unused columns
    op.drop_column("prompt_templates", "version")
    op.drop_column("prompt_templates", "prompt_type")
    op.drop_column("prompt_templates", "is_active")
    op.drop_column("prompt_templates", "change_reason")
    op.drop_column("prompt_templates", "prompt_metadata")
    op.drop_column("prompt_templates", "created_by")

    # Add new unique constraint on name alone
    op.create_unique_constraint("uq_prompt_templates_name", "prompt_templates", ["name"])


def downgrade() -> None:
    """Restore original prompt_templates schema."""
    op.drop_constraint("uq_prompt_templates_name", "prompt_templates")

    # Restore dropped columns
    op.add_column(
        "prompt_templates",
        sa.Column("created_by", sa.String(100), server_default="system", nullable=False),
    )
    op.add_column(
        "prompt_templates",
        sa.Column("prompt_metadata", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "prompt_templates",
        sa.Column("change_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "prompt_templates",
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "prompt_templates",
        sa.Column("prompt_type", sa.String(20), nullable=False),
    )
    op.add_column(
        "prompt_templates",
        sa.Column("version", sa.String(20), nullable=False),
    )

    # Rename template → content
    op.alter_column("prompt_templates", "template", new_column_name="content")

    # Restore old constraints and indexes
    op.create_unique_constraint("uq_prompt_name_version", "prompt_templates", ["name", "version"])
    op.create_index("idx_prompt_templates_name", "prompt_templates", ["name"])
    op.create_index(
        "idx_prompt_templates_created_at",
        "prompt_templates",
        [sa.text("created_at DESC")],
    )
