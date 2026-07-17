# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Add payload_hash column to alert_events for 24h dedup (T018 / R-alert-002).

Revision ID: 33_add_alert_events_payload_hash
Revises: 32_extend_daily_briefings_for_category
Create Date: 2026-07-17

Changes:
- alert_events: add payload_hash (VARCHAR(64), nullable)
  Stores sha256 hex digest of the normalized alert payload (JSON keys
  sorted ascending, ensure_ascii=False). Used by TrendAlertEvaluator for
  24h dedup: before inserting a new event, the evaluator queries
  alert_events WHERE rule_id=? AND payload_hash=? AND triggered_at > now()-24h.
  If a matching event exists, the new event is skipped (no duplicate alerts
  within 24h for the same rule + payload).
- alert_events: add composite index idx_alert_events_payload_hash on
  (rule_id, payload_hash, triggered_at) to accelerate the dedup query.
  The query filters by rule_id (equality), payload_hash (equality), and
  triggered_at (range > now()-24h) — a composite index on all 3 columns
  in this order enables an index-only scan for the dedup check.

Background:
- T018 TrendAlertEvaluator triggers alerts based on trend_spike / trend_drop
  / sentiment_shift rules. Without dedup, the hourly scheduler would
  re-insert identical alerts every hour as long as the trend persists,
  flooding the alert_events table.
- payload_hash is nullable to preserve backward compatibility with
  pre-migration rows (existing alert_events rows have NULL payload_hash
  and are not subject to dedup).

Cross-database compatibility (Rule — PG + DuckDB):
- VARCHAR(64) is supported by both PostgreSQL and DuckDB.
- sha256 hex digest is always 64 chars, so VARCHAR(64) is exact (no truncation).
- Composite index syntax is standard SQL, supported by both databases.

Downgrade safety:
- Downgrade drops the index FIRST, then the column. Order matters:
  if DROP COLUMN runs before DROP INDEX, the index drop fails because
  the column no longer exists.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "33_add_alert_events_payload_hash"
down_revision: str | None = "32_extend_daily_briefings_for_category"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add payload_hash column + composite index to alert_events."""
    # payload_hash: sha256 hex digest of normalized alert payload.
    # Nullable for backward compat with pre-migration rows.
    op.add_column(
        "alert_events",
        sa.Column("payload_hash", sa.String(64), nullable=True),
    )

    # Composite index for 24h dedup query:
    #   WHERE rule_id=? AND payload_hash=? AND triggered_at > now()-24h
    # Column order (rule_id, payload_hash, triggered_at) matches equality
    # predicates first, then range predicate, enabling efficient index scan.
    op.create_index(
        "idx_alert_events_payload_hash",
        "alert_events",
        ["rule_id", "payload_hash", "triggered_at"],
    )


def downgrade() -> None:
    """Drop index first, then column (reverse order of upgrade).

    Order matters: DROP INDEX must run BEFORE DROP COLUMN, otherwise
    the index drop fails because the column no longer exists.
    """
    # 1. Drop the composite index
    op.drop_index("idx_alert_events_payload_hash", table_name="alert_events")

    # 2. Drop the payload_hash column
    op.drop_column("alert_events", "payload_hash")
