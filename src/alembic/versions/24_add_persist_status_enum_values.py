# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add missing values to persist_status ENUM.

Revision ID: 24_add_persist_status_enum_values
Revises: 23_seed_relation_types
Create Date: 2026-06-22

Changes:
- persist_status ENUM: add ladybug_done and saga_* values to match Python PersistStatus enum
- Required for queue_stats queries that use completed_statuses() which includes ladybug_done and saga_completed
"""

from collections.abc import Sequence

from alembic import op

revision: str = "24_add_persist_status_enum_values"
down_revision: str | None = "23_seed_relation_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add missing persist_status ENUM values.

    PostgreSQL does not support adding ENUM values inside a transaction,
    so we use ALTER TYPE ... ADD VALUE which auto-commits.
    """
    # LadybugDB terminal success state
    op.execute("ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'ladybug_done'")

    # Saga states for cross-database transactions
    op.execute("ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_started'")
    op.execute("ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_pg_writing'")
    op.execute("ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_neo4j_writing'")
    op.execute("ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_compensating'")
    op.execute("ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_compensated'")
    op.execute("ALTER TYPE persist_status ADD VALUE IF NOT EXISTS 'saga_completed'")


def downgrade() -> None:
    """Revert ENUM changes (PostgreSQL does not support removing ENUM values)."""
    # Note: PostgreSQL does not support removing ENUM values.
    # The only way to revert is to recreate the type, which is risky.
    pass
