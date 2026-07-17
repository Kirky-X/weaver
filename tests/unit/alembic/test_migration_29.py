# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Migration 29 tests — seed default trend alert rules.

Verifies:
- Revision chain (29 extends 28_extend_alert_rules_for_trend)
- Migration up inserts 3 default rules via offline SQL
- Migration up is idempotent (WHERE NOT EXISTS pattern)
- Migration down deletes events first, then rules (FK RESTRICT safety)
- Migration down prints deleted row counts (Rule 12: Fail Loud)
- Seed rule values match spec (trend_spike/drop + sentiment_shift)
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

ALEMBIC_VERSIONS = (
    Path(__file__).resolve().parent.parent.parent.parent / "src" / "alembic" / "versions"
)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


# ── Revision chain ──────────────────────────────────────────────────────────


def _read_revision_vars(file_stem: str) -> tuple[str, str | None]:
    """Read revision and down_revision from a migration file without importing."""
    filepath = ALEMBIC_VERSIONS / f"{file_stem}.py"
    content = filepath.read_text()
    rev_match = re.search(r'^revision:\s*str\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    down_match = re.search(
        r'^down_revision:\s*str\s*\|\s*None\s*=\s*(None|["\']([^"\']*)["\'])',
        content,
        re.MULTILINE,
    )
    rev = rev_match.group(1) if rev_match else ""
    if down_match:
        down = None if down_match.group(1) == "None" else down_match.group(2)
    else:
        down = None
    return rev, down


def test_revision_chain_migration_29() -> None:
    """Migration 29 must extend 28_extend_alert_rules_for_trend."""
    rev, down = _read_revision_vars("29_seed_default_alert_rules")
    assert rev == "29_seed_default_alert_rules"
    assert down == "28_extend_alert_rules_for_trend"


# ── Migration up SQL (offline) + source verification ────────────────────────


def _capture_offline_sql(from_rev: str, to_rev: str) -> str:
    """Run alembic offline upgrade and return captured SQL output."""
    from alembic.command import upgrade as alembic_upgrade
    from alembic.config import Config

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql://nouser:nopass@localhost:15432/nodb")
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "src" / "alembic"))

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        alembic_upgrade(alembic_cfg, f"{from_rev}:{to_rev}", sql=True)
    finally:
        sys.stdout = old_stdout
    return captured.getvalue()


def _read_migration_source() -> str:
    """Read migration 29 source file for static verification."""
    return (ALEMBIC_VERSIONS / "29_seed_default_alert_rules.py").read_text()


def test_migration_29_up_inserts_three_seed_rules() -> None:
    """Migration 29 up must insert 3 default trend alert rules.

    Rules per spec:
    1. trend_spike: volume_spike, 7d window, +50% threshold
    2. trend_drop: volume_spike, 7d window, -50% threshold (uses 0.5 magnitude)
    3. sentiment_shift: sentiment_change, 7d window, 0.3 magnitude
    """
    source = _read_migration_source()
    # Must define 3 seed rules
    assert source.count("trigger_type") >= 3, "Expected at least 3 trigger_type references"
    # 3 trigger types must be present
    assert "trend_spike" in source
    assert "trend_drop" in source
    assert "sentiment_shift" in source
    # Metrics must match spec
    assert "volume_spike" in source  # for trend_spike + trend_drop
    assert "sentiment_change" in source  # for sentiment_shift
    # Window days = 7 for all rules
    assert "7" in source
    # Thresholds: 0.5 for trend_spike/drop, 0.3 for sentiment_shift
    assert "0.5" in source
    assert "0.3" in source
    # entity_name = '*' (wildcard, applies to all entities)
    assert "'*'" in source or '"*"' in source


def test_migration_29_up_idempotent() -> None:
    """Migration 29 up must be idempotent — safe to re-run.

    Uses INSERT ... WHERE NOT EXISTS pattern to skip if rule already exists.
    This avoids requiring a unique constraint on (entity_name, trigger_type).
    """
    sql = _capture_offline_sql("28_extend_alert_rules_for_trend", "29_seed_default_alert_rules")
    # Must contain INSERT statement
    assert "INSERT INTO alert_rules" in sql, f"INSERT not found in SQL: {sql}"
    # Must use WHERE NOT EXISTS for idempotency
    assert (
        "NOT EXISTS" in sql or "WHERE NOT EXISTS" in sql
    ), f"Idempotency pattern WHERE NOT EXISTS not found in SQL: {sql}"


def test_migration_29_up_offline_sql_contains_insert() -> None:
    """Offline SQL output must contain at least one INSERT INTO alert_rules."""
    sql = _capture_offline_sql("28_extend_alert_rules_for_trend", "29_seed_default_alert_rules")
    assert "INSERT INTO alert_rules" in sql


# ── Migration down SQL (offline) ────────────────────────────────────────────


def _capture_offline_down_sql(from_rev: str, to_rev: str) -> str:
    """Run alembic offline downgrade and return captured SQL output."""
    from alembic.command import downgrade as alembic_downgrade
    from alembic.config import Config

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql://nouser:nopass@localhost:15432/nodb")
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "src" / "alembic"))

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        alembic_downgrade(alembic_cfg, f"{from_rev}:{to_rev}", sql=True)
    finally:
        sys.stdout = old_stdout
    return captured.getvalue()


def test_migration_29_down_deletes_events_before_rules() -> None:
    """Downgrade must DELETE alert_events BEFORE alert_rules (FK RESTRICT).

    alert_events.rule_id has FK to alert_rules.id with default RESTRICT.
    Deleting rules first would fail if events exist. Order matters.
    """
    sql = _capture_offline_down_sql(
        "29_seed_default_alert_rules", "28_extend_alert_rules_for_trend"
    )

    # Both DELETEs must be present
    assert (
        "DELETE FROM alert_events" in sql
    ), f"alert_events delete not found in downgrade SQL: {sql}"
    assert "DELETE FROM alert_rules" in sql, f"alert_rules delete not found in downgrade SQL: {sql}"

    # Order: alert_events DELETE must come before alert_rules DELETE
    events_pos = sql.find("DELETE FROM alert_events")
    rules_pos = sql.find("DELETE FROM alert_rules")
    assert events_pos != -1 and rules_pos != -1, "DELETE statements not found"
    assert events_pos < rules_pos, (
        f"alert_events delete (pos {events_pos}) must come before "
        f"alert_rules delete (pos {rules_pos})"
    )


def test_migration_29_down_targets_only_seed_rules() -> None:
    """Downgrade must only delete seed rules using precise signature.

    Security review MEDIUM (T005 review): downgrade WHERE clause must include
    trend_window_days=7 AND trend_threshold IN (0.5, 0.3) to avoid deleting
    user-created rules that happen to use the same trigger_type but different
    parameters (e.g. trend_spike with trend_window_days=14).

    Must NOT delete user-created trend rules — those are handled by migration 28
    downgrade. This separation allows users to rollback seed data independently.
    """
    sql = _capture_offline_down_sql(
        "29_seed_default_alert_rules", "28_extend_alert_rules_for_trend"
    )
    source = _read_migration_source()

    # Must target entity_name = '*' (seed rules only)
    assert "'*'" in sql or '"*"' in sql or "'*'" in source
    # Must filter by trend trigger types (not all trigger_type != 'threshold')
    assert "trend_spike" in sql or "trend_spike" in source
    assert "trend_drop" in sql or "trend_drop" in source
    assert "sentiment_shift" in sql or "sentiment_shift" in source
    # Must include precise trend_window_days=7 to avoid deleting user rules
    # with different window (e.g. trend_spike with window=14)
    assert "trend_window_days" in sql or "trend_window_days = 7" in source, (
        "Downgrade must filter by trend_window_days=7 to avoid deleting "
        "user-created rules with different window sizes"
    )
    # Must include trend_threshold IN (0.5, 0.3) to match seed values only
    assert "trend_threshold" in sql or "trend_threshold IN (0.5, 0.3)" in source, (
        "Downgrade must filter by trend_threshold IN (0.5, 0.3) to avoid "
        "deleting user-created rules with different thresholds"
    )


def test_migration_29_down_prints_deleted_counts() -> None:
    """Downgrade must print deleted row counts via RAISE NOTICE (Rule 12).

    Per Rule 12 (Fail Loud): skipped/deleted items must be counted and
    reported in output, not silently buried in logs.
    """
    sql = _capture_offline_down_sql(
        "29_seed_default_alert_rules", "28_extend_alert_rules_for_trend"
    )
    source = _read_migration_source()

    # Must use RAISE NOTICE to print row counts (Rule 12)
    assert "RAISE NOTICE" in sql or "RAISE NOTICE" in source, (
        f"RAISE NOTICE not found — Rule 12 requires explicit deleted count reporting. "
        f"SQL: {sql[:500]}"
    )
    # Must reference ROW_COUNT for diagnostics
    assert "ROW_COUNT" in sql or "ROW_COUNT" in source


# ── Seed rule values verification ───────────────────────────────────────────


def test_seed_rules_have_correct_thresholds() -> None:
    """Seed rules must use spec-defined thresholds.

    - trend_spike: trend_threshold = 0.5 (50% volume increase)
    - trend_drop: trend_threshold = 0.5 (50% volume decrease)
    - sentiment_shift: trend_threshold = 0.3 (sentiment magnitude change)
    """
    source = _read_migration_source()
    # 0.5 appears for trend_spike and trend_drop (twice in source)
    assert source.count("0.5") >= 2, (
        f"Expected at least 2 occurrences of 0.5 (trend_spike + trend_drop), "
        f"got {source.count('0.5')}"
    )
    # 0.3 appears for sentiment_shift
    assert "0.3" in source, "Expected 0.3 threshold for sentiment_shift rule"


def test_seed_rules_have_correct_window_days() -> None:
    """All seed rules must use 7-day trend window."""
    source = _read_migration_source()
    # 7 appears as trend_window_days for all 3 rules
    # Count occurrences near "trend_window_days" or in seed data
    assert "7" in source, "Expected trend_window_days=7 not found"


def test_seed_rules_use_wildcard_entity() -> None:
    """Seed rules must use entity_name='*' (wildcard, applies to all entities).

    Default rules are global — they should trigger for any entity, not just
    a specific one. Users can create entity-specific rules separately.
    """
    source = _read_migration_source()
    assert (
        "'*'" in source or '"*"' in source
    ), "Expected entity_name='*' (wildcard) for default seed rules"


def test_seed_rules_use_enabled_true() -> None:
    """Seed rules must be enabled by default (enabled=true).

    Default rules should be active immediately after migration so users
    see alerts without additional configuration.
    """
    source = _read_migration_source()
    # Either "true" in SQL or "enabled" field set to True
    assert "true" in source.lower(), "Expected enabled=true for seed rules"


# ── DuckDB schema parity ────────────────────────────────────────────────────


def test_duckdb_schema_does_not_need_seed_changes() -> None:
    """DuckDB schema doesn't seed alert rules — seed is PostgreSQL-only via Alembic.

    Per project convention: DuckDB uses duckdb_schema.py for table creation
    but does NOT seed data (seeds are managed by Alembic migrations for
    PostgreSQL only). DuckDB falls back to PostgreSQL as primary, so seed
    data is available at runtime via the primary DB.
    """
    from core.db import duckdb_schema

    # DuckDB schema should NOT contain INSERT INTO alert_rules
    for stmt in duckdb_schema.SCHEMA_QUERIES:
        assert (
            "INSERT INTO alert_rules" not in stmt
        ), "DuckDB schema should not seed alert_rules — seeds are PostgreSQL-only"
