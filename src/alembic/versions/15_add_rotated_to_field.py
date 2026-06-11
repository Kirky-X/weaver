# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Add rotated_to field to api_keys table for key rotation tracking.

Revision ID: 15_add_rotated_to_field
Revises: 14_add_check_constraints
Create Date: 2026-06-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "15_add_rotated_to_field"
down_revision: str | None = "14_add_check_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add rotated_to column to api_keys table."""
    op.add_column("api_keys", sa.Column("rotated_to", sa.String(64), nullable=True))


def downgrade() -> None:
    """Drop rotated_to column from api_keys table."""
    op.drop_column("api_keys", "rotated_to")
