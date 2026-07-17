# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Seed default alert rules for trend triggers.

Revision ID: 29_seed_default_alert_rules
Revises: 28_extend_alert_rules_for_trend
Create Date: 2026-07-17

Changes:
- Insert 3 default trend alert rules (idempotent):
  1. trend_spike: volume_spike, 7d window, +50% threshold (trend_threshold=0.5)
  2. trend_drop: volume_spike, 7d window, -50% threshold (trend_threshold=0.5)
  3. sentiment_shift: sentiment_change, 7d window, magnitude 0.3

Idempotency:
- Uses INSERT ... SELECT ... WHERE NOT EXISTS pattern to avoid duplicate
  inserts on re-runs. No unique constraint on (entity_name, trigger_type)
  required — the WHERE NOT EXISTS subquery provides the guard.

Downgrade safety:
- Downgrade first DELETEs alert_events referencing seeded rules (FK NO
  ACTION on alert_events.rule_id → alert_rules.id, behaviorally equivalent
  to RESTRICT for non-deferred constraints), then DELETEs the 3 seeded
  rules. Per Rule 12 (Fail Loud), prints deleted row counts via RAISE NOTICE.
- Seeded rules are identified by a precise signature:
    entity_name='*' AND trigger_type IN ('trend_spike','trend_drop','sentiment_shift')
    AND trend_window_days=7 AND trend_threshold IN (0.5, 0.3)
  This avoids deleting user-created rules that happen to use the same
  trigger_type but different parameters (e.g. a user-created trend_spike
  rule with trend_window_days=14). User-created trend rules are handled
  by migration 28 downgrade (trigger_type != 'threshold').

Note on metric/operator/threshold:
- trend rules primarily use trigger_type + trend_window_days + trend_threshold.
- metric/operator/threshold are NOT NULL columns inherited from the original
  schema (migration 08), so trend rules use placeholder values
  (threshold=0) to satisfy the NOT NULL constraint.
- The TrendAlertEvaluator (T018, not yet implemented) will read trigger_type
  + trend_* fields, ignoring the legacy threshold. Until T018 is implemented,
  these seed rules have no consumer — they are inert data that satisfies
  all CHECK constraints but triggers no alerts.
- T018 must handle direction: trend_spike → pct_change > +threshold;
  trend_drop → pct_change < -threshold; sentiment_shift → |change| > threshold.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "29_seed_default_alert_rules"
down_revision: str | None = "28_extend_alert_rules_for_trend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Seed rule definitions — hardcoded constants (no user input, SQL-safe).
# Kept as module-level data so tests can statically verify values without
# running the migration against a live DB.
_SEED_RULES: list[dict[str, object]] = [
    {
        "entity_name": "*",
        "metric": "volume_spike",
        "operator": "pct_change>",
        "threshold": 0,
        "trigger_type": "trend_spike",
        "trend_window_days": 7,
        "trend_threshold": 0.5,
    },
    {
        "entity_name": "*",
        "metric": "volume_spike",
        "operator": "pct_change>",
        "threshold": 0,
        "trigger_type": "trend_drop",
        "trend_window_days": 7,
        "trend_threshold": 0.5,
    },
    {
        "entity_name": "*",
        "metric": "sentiment_change",
        "operator": "absolute>",
        "threshold": 0,
        "trigger_type": "sentiment_shift",
        "trend_window_days": 7,
        "trend_threshold": 0.3,
    },
]

# Idempotent INSERT — skips if a rule with the same (entity_name, trigger_type)
# already exists. Uses parameterized SQL via sa.text().bindparams() for SQL
# injection safety (even though values are constants, follow project convention).
_INSERT_SQL = """
INSERT INTO alert_rules
    (entity_name, metric, operator, threshold, channel,
     cooldown_minutes, enabled, trigger_type,
     trend_window_days, trend_threshold)
SELECT
    :entity_name, :metric, :operator, :threshold, 'webhook',
    60, true, :trigger_type,
    :trend_window_days, :trend_threshold
WHERE NOT EXISTS (
    SELECT 1 FROM alert_rules
    WHERE entity_name = :entity_name
      AND trigger_type = :trigger_type
)
"""

# Downgrade — deletes events first (FK NO ACTION), then seed rules.
# Row counts printed via RAISE NOTICE per Rule 12 (Fail Loud).
# Targets only seed rules using precise signature (entity_name='*' + trend
# trigger_types + trend_window_days=7 + trend_threshold IN 0.5/0.3) to avoid
# deleting user-created rules with same trigger_type but different params.
# User-created trend rules are preserved (handled by migration 28 downgrade).
_DOWNGRADE_SQL = """
DO $$ DECLARE
    deleted_events INTEGER;
    deleted_rules INTEGER;
BEGIN
    DELETE FROM alert_events
    WHERE rule_id IN (
        SELECT id FROM alert_rules
        WHERE entity_name = '*'
          AND trigger_type IN ('trend_spike', 'trend_drop', 'sentiment_shift')
          AND trend_window_days = 7
          AND trend_threshold IN (0.5, 0.3)
    );
    GET DIAGNOSTICS deleted_events = ROW_COUNT;

    DELETE FROM alert_rules
    WHERE entity_name = '*'
      AND trigger_type IN ('trend_spike', 'trend_drop', 'sentiment_shift')
      AND trend_window_days = 7
      AND trend_threshold IN (0.5, 0.3);
    GET DIAGNOSTICS deleted_rules = ROW_COUNT;

    RAISE NOTICE 'Migration 29 downgrade: deleted % alert events, % seed rules',
        deleted_events, deleted_rules;
END $$
"""


def upgrade() -> None:
    """Seed 3 default trend alert rules (idempotent via WHERE NOT EXISTS)."""
    for rule in _SEED_RULES:
        op.execute(sa.text(_INSERT_SQL).bindparams(**rule))


def downgrade() -> None:
    """Remove seeded alert rules and their events.

    Order: alert_events first (FK RESTRICT safety), then alert_rules.
    Prints deleted counts via RAISE NOTICE (Rule 12: Fail Loud).
    Only targets seed rules — user-created trend rules are preserved.
    """
    op.execute(sa.text(_DOWNGRADE_SQL))
