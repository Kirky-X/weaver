# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Create event_outbox table for transactional outbox.

Revision ID: 35_add_event_outbox
Revises: 34_add_articles_core_title_index
Create Date: 2026-09-14

Changes:
- event_outbox: at-least-once domain event delivery without a message
  broker. MemoryIngestEvent rows are persisted before dispatch and
  replayed by the dispatch_outbox_events scheduler job.

Columns:
- id: monotonically increasing dispatch order
- event_type: event class name
- article_id: optional correlation id
- payload: JSONCompatible event payload
- status: 'pending' -> 'dispatched' | 'dead' (retries exhausted)
- retry_count / last_error: failure accounting
- created_at / dispatched_at: lifecycle timestamps
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "35_add_event_outbox"
down_revision: str | None = "34_add_articles_core_title_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create event_outbox with a (status, created_at) dispatch index."""
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_event_outbox_status_created",
        "event_outbox",
        ["status", "created_at"],
    )


def downgrade() -> None:
    """Drop the event_outbox table."""
    op.drop_index("idx_event_outbox_status_created", table_name="event_outbox")
    op.drop_table("event_outbox")
