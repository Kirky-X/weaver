# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Create alert_rules and alert_events tables.

Revision ID: 08_create_alert_tables
Revises: 07_create_api_keys_table
Create Date: 2026-06-10

Changes per Weaver-数据库设计文档 §12.4:
- Create alert_rules table with CHECK constraints on metric and operator
- Create alert_events table with FK to alert_rules
- Indexes on triggered_at DESC and (entity_name, triggered_at DESC)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "08_create_alert_tables"
down_revision: str | None = "07_create_api_keys_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create alert_rules and alert_events tables."""
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entity_name", sa.String(200), nullable=False),
        sa.Column("metric", sa.String(50), nullable=False),
        sa.Column("operator", sa.String(20), nullable=False),
        sa.Column("threshold", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "channel",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'webhook'"),
        ),
        sa.Column(
            "cooldown_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "metric IN ('reference_count', 'sentiment_change', 'volume_spike')",
            name="chk_alert_metric_values",
        ),
        sa.CheckConstraint(
            "operator IN ('z_score>', 'pct_change>', 'absolute>')",
            name="chk_alert_operator_values",
        ),
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "rule_id",
            sa.BigInteger(),
            sa.ForeignKey("alert_rules.id"),
            nullable=False,
        ),
        sa.Column("entity_name", sa.String(200), nullable=False),
        sa.Column("metric_value", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "idx_alert_events_triggered",
        "alert_events",
        [sa.text("triggered_at DESC")],
    )
    op.create_index(
        "idx_alert_events_entity",
        "alert_events",
        ["entity_name", sa.text("triggered_at DESC")],
    )


def downgrade() -> None:
    """Drop alert tables."""
    op.drop_index("idx_alert_events_entity", table_name="alert_events")
    op.drop_index("idx_alert_events_triggered", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
