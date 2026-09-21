# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Extend alert_rules CHECK constraint to include saga metrics.

Revision ID: 36_extend_alert_metrics
Revises: 35_add_event_outbox
Create Date: 2026-09-14

Changes:
- Extend chk_alert_metric_values CHECK constraint on alert_rules table
  to include saga_failure, compensation_failure, saga_timeout metrics
  used by src/core/saga/alerts.py

Background:
- Original constraint (migration 08) only allowed: reference_count,
  sentiment_change, volume_spike
- Saga alert system (core/saga/alerts.py) uses three additional metrics
  that were never added to the constraint, causing INSERT failures
"""

from collections.abc import Sequence

from alembic import op

revision: str = "36_extend_alert_metrics"
down_revision: str | None = "35_add_event_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend chk_alert_metric_values to include saga metrics."""
    op.drop_constraint("chk_alert_metric_values", "alert_rules", type_="check")
    op.create_check_constraint(
        "chk_alert_metric_values",
        "alert_rules",
        "metric IN ('reference_count', 'sentiment_change', 'volume_spike', "
        "'saga_failure', 'compensation_failure', 'saga_timeout')",
    )


def downgrade() -> None:
    """Revert chk_alert_metric_values to original 3-value constraint."""
    op.drop_constraint("chk_alert_metric_values", "alert_rules", type_="check")
    op.create_check_constraint(
        "chk_alert_metric_values",
        "alert_rules",
        "metric IN ('reference_count', 'sentiment_change', 'volume_spike')",
    )
