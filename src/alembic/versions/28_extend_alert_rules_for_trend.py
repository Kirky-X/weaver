# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Extend alert_rules table for trend-based triggers.

Revision ID: 28_extend_alert_rules_for_trend
Revises: 27_create_llm_compare_hourly
Create Date: 2026-07-17

Changes:
- alert_rules: add trigger_type (VARCHAR(20), default 'threshold')
- alert_rules: add trend_window_days (INTEGER, nullable)
- alert_rules: add trend_threshold (NUMERIC(10,2), nullable)
- alert_rules: add CHECK constraint chk_alert_trigger_type_values allowing
  values: threshold, trend_spike, trend_drop, sentiment_shift

Background:
- Existing rules use metric/operator/threshold fields (trigger_type defaults
  to 'threshold', preserving backward compatibility).
- New trend rules (added by migration 29 seed + TrendAlertEvaluator T018)
  use trigger_type='trend_spike'|'trend_drop'|'sentiment_shift' with
  trend_window_days + trend_threshold.
- trigger_type uses VARCHAR + CHECK (not PostgreSQL ENUM) for DuckDB
  compatibility (DuckDB does not support ENUM, uses VARCHAR+CHECK per
  project convention).

Downgrade safety:
- Downgrade first DELETEs all rules where trigger_type != 'threshold'
  (removes both migration 29 seed rules AND any user-created trend rules),
  then drops the CHECK constraints and 3 columns. This order avoids
  leaving orphaned trend rules that would violate the dropped CHECK
  constraint semantics. The DELETE is broad by design — trend rules
  cannot exist without the trigger_type column being downgraded.
- Per Rule 12 (Fail Loud), the DELETE row count is printed via RAISE
  NOTICE so operators can verify how many trend rules were removed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "28_extend_alert_rules_for_trend"
down_revision: str | None = "27_create_llm_compare_hourly"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 3 columns + CHECK constraints to alert_rules."""
    # trigger_type: distinguishes threshold rules from trend rules
    op.add_column(
        "alert_rules",
        sa.Column(
            "trigger_type",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'threshold'"),
        ),
    )
    # trend_window_days: window in days for trend calculation (nullable,
    # only used by trend_spike/trend_drop rules)
    op.add_column(
        "alert_rules",
        sa.Column("trend_window_days", sa.Integer(), nullable=True),
    )
    # trend_threshold: percentage change (e.g. 0.5 = +50%) or sentiment
    # shift magnitude (e.g. 0.3). Nullable, only used by trend rules.
    op.add_column(
        "alert_rules",
        sa.Column("trend_threshold", sa.Numeric(10, 2), nullable=True),
    )

    # CHECK constraint on trigger_type — allows 4 values
    op.create_check_constraint(
        "chk_alert_trigger_type_values",
        "alert_rules",
        "trigger_type IN ('threshold', 'trend_spike', 'trend_drop', 'sentiment_shift')",
    )

    # Composite CHECK: trend rules must have both trend_window_days and
    # trend_threshold populated. Prevents half-broken trend rules.
    op.create_check_constraint(
        "chk_alert_trend_fields_required",
        "alert_rules",
        "trigger_type = 'threshold' OR (trend_window_days IS NOT NULL "
        "AND trend_threshold IS NOT NULL)",
    )


def downgrade() -> None:
    """Remove trend rules, CHECK constraints, and 3 columns.

    Order matters:
    1. DELETE alert_events referencing trend rules first (FK NO ACTION,
       behaviorally equivalent to RESTRICT for non-deferred constraints).
       Without this, DELETE FROM alert_rules would fail if any trend rule
       has generated alert_events.
    2. DELETE trend rules (trigger_type != 'threshold') to clean data
       that references the soon-to-be-dropped columns. Includes both
       migration 29 seed rules and any user-created trend rules.
    3. DROP CHECK constraints (trigger_type values + trend fields required).
    4. DROP 3 columns.
    """
    # 1+2. Delete events first, then rules — print row counts (Rule 12)
    op.execute(
        "DO $$ DECLARE "
        "deleted_events INTEGER; "
        "deleted_rules INTEGER; "
        "BEGIN "
        "DELETE FROM alert_events WHERE rule_id IN "
        "(SELECT id FROM alert_rules WHERE trigger_type != 'threshold'); "
        "GET DIAGNOSTICS deleted_events = ROW_COUNT; "
        "DELETE FROM alert_rules WHERE trigger_type != 'threshold'; "
        "GET DIAGNOSTICS deleted_rules = ROW_COUNT; "
        "RAISE NOTICE 'Migration 28 downgrade: deleted % alert events, % trend rules', "
        "deleted_events, deleted_rules; "
        "END $$"
    )

    # 3. Drop CHECK constraints
    op.drop_constraint("chk_alert_trend_fields_required", "alert_rules", type_="check")
    op.drop_constraint("chk_alert_trigger_type_values", "alert_rules", type_="check")

    # 4. Drop columns (reverse order of upgrade)
    op.drop_column("alert_rules", "trend_threshold")
    op.drop_column("alert_rules", "trend_window_days")
    op.drop_column("alert_rules", "trigger_type")
