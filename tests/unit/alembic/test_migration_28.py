# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Migration 28 tests — extend alert_rules for trend triggers.

Verifies:
- Revision chain (28 extends 27_create_llm_compare_hourly)
- Migration up adds 3 columns + CHECK constraint via offline SQL
- Migration down removes data + columns + constraint via offline SQL
- ORM AlertRule has new fields with correct types and defaults
- DuckDB schema includes new columns
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


def test_revision_chain_migration_28() -> None:
    """Migration 28 must extend 27_create_llm_compare_hourly."""
    rev, down = _read_revision_vars("28_extend_alert_rules_for_trend")
    assert rev == "28_extend_alert_rules_for_trend"
    assert down == "27_create_llm_compare_hourly"


# ── Migration up SQL (offline) ──────────────────────────────────────────────


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


def test_migration_28_up_adds_columns_and_check() -> None:
    """Migration 28 up must add 3 columns + CHECK constraint to alert_rules."""
    sql = _capture_offline_sql("27_create_llm_compare_hourly", "28_extend_alert_rules_for_trend")

    # 3 new columns added
    assert "ADD COLUMN" in sql or "add_column" in sql.lower()
    assert "trigger_type" in sql
    assert "trend_window_days" in sql
    assert "trend_threshold" in sql

    # Default value for trigger_type must be 'threshold'
    assert "'threshold'" in sql

    # CHECK constraint for trigger_type values
    assert "trend_spike" in sql
    assert "trend_drop" in sql
    assert "sentiment_shift" in sql
    assert "threshold" in sql
    # Constraint name follows existing chk_alert_* convention
    assert "chk_alert_trigger_type_values" in sql or "trigger_type_values" in sql


def test_migration_28_down_removes_columns_and_data() -> None:
    """Migration 28 down must delete trend rules then drop columns + constraint.

    Per task spec: down must DELETE FROM alert_rules WHERE trigger_type != 'threshold'
    BEFORE dropping columns (otherwise FK from alert_events or CHECK constraint
    would fail).
    """
    from alembic.command import downgrade as alembic_downgrade
    from alembic.config import Config

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql://nouser:nopass@localhost:15432/nodb")
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "src" / "alembic"))

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        alembic_downgrade(
            alembic_cfg, "28_extend_alert_rules_for_trend:27_create_llm_compare_hourly", sql=True
        )
    finally:
        sys.stdout = old_stdout
    sql = captured.getvalue()

    # Delete trend rules BEFORE dropping columns (order matters)
    assert "DELETE FROM alert_rules" in sql
    assert "trigger_type" in sql
    assert "threshold" in sql

    # Drop CHECK constraint
    assert "DROP CONSTRAINT" in sql or "drop_constraint" in sql.lower()

    # Drop 3 columns
    assert "DROP COLUMN" in sql or "drop_column" in sql.lower()
    assert "trigger_type" in sql
    assert "trend_window_days" in sql
    assert "trend_threshold" in sql


# ── ORM field verification ──────────────────────────────────────────────────


def test_alert_rule_orm_has_new_fields() -> None:
    """AlertRule ORM must expose trigger_type, trend_window_days, trend_threshold."""
    from core.db.models.alert import AlertRule

    # New fields must exist as Mapped attributes
    assert hasattr(AlertRule, "trigger_type"), "AlertRule missing trigger_type"
    assert hasattr(AlertRule, "trend_window_days"), "AlertRule missing trend_window_days"
    assert hasattr(AlertRule, "trend_threshold"), "AlertRule missing trend_threshold"


def test_alert_rule_orm_field_types() -> None:
    """AlertRule new fields must have correct SQLAlchemy types."""
    from sqlalchemy import Float, Integer, Numeric, String

    from core.db.models.alert import AlertRule

    # trigger_type: String(20) with default 'threshold'
    trigger_col = AlertRule.__table__.columns["trigger_type"]
    assert isinstance(trigger_col.type, String)
    assert trigger_col.type.length == 20
    assert trigger_col.nullable is False  # has default
    # Default value must be 'threshold' (server_default)
    server_default = str(trigger_col.server_default.arg) if trigger_col.server_default else ""
    assert "threshold" in server_default or trigger_col.default is not None

    # trend_window_days: Integer, nullable
    window_col = AlertRule.__table__.columns["trend_window_days"]
    assert isinstance(window_col.type, Integer)
    assert window_col.nullable is True

    # trend_threshold: Numeric or Float, nullable
    threshold_col = AlertRule.__table__.columns["trend_threshold"]
    assert isinstance(threshold_col.type, (Numeric, Float))
    assert threshold_col.nullable is True


def test_alert_rule_orm_has_trigger_type_check_constraint() -> None:
    """AlertRule must have CHECK constraint allowing 4 trigger_type values."""
    from core.db.models.alert import AlertRule

    check_constraints = [
        str(c.sqltext)
        for c in AlertRule.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    ]
    # Find the trigger_type check constraint
    trigger_checks = [
        c for c in check_constraints if "trigger_type" in c and "trend_window_days" not in c
    ]
    assert len(trigger_checks) == 1, f"Expected 1 trigger_type CHECK, got {len(trigger_checks)}"
    check_sql = trigger_checks[0]
    assert "threshold" in check_sql
    assert "trend_spike" in check_sql
    assert "trend_drop" in check_sql
    assert "sentiment_shift" in check_sql


def test_alert_rule_orm_has_trend_fields_required_check() -> None:
    """AlertRule must have composite CHECK requiring trend fields for trend rules.

    Architecture review M1: trend rules (trigger_type != 'threshold') must
    have both trend_window_days and trend_threshold populated. Prevents
    half-broken trend rules from seed scripts or API writes.
    """
    from core.db.models.alert import AlertRule

    check_constraints = [
        str(c.sqltext)
        for c in AlertRule.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    ]
    # Find the composite check (contains both trigger_type and trend_window_days)
    composite_checks = [
        c for c in check_constraints if "trigger_type" in c and "trend_window_days" in c
    ]
    assert len(composite_checks) == 1, (
        f"Expected 1 composite CHECK, got {len(composite_checks)}. "
        f"All checks: {check_constraints}"
    )
    check_sql = composite_checks[0]
    assert "threshold" in check_sql
    assert "trend_window_days" in check_sql
    assert "trend_threshold" in check_sql
    assert "IS NOT NULL" in check_sql


# ── DuckDB schema verification ──────────────────────────────────────────────


def test_duckdb_schema_has_new_alert_rules_columns() -> None:
    """DuckDB alert_rules schema must include 3 new columns + CHECK constraints.

    Security review H1: DuckDB must have CHECK constraint on trigger_type
    to match PostgreSQL (project convention: VARCHAR+CHECK for DuckDB).
    Architecture review M2: dual-database semantic symmetry.
    """
    from core.db import duckdb_schema

    # Find the alert_rules CREATE TABLE statement
    alert_rules_stmt = None
    for stmt in duckdb_schema.SCHEMA_QUERIES:
        if "CREATE TABLE IF NOT EXISTS alert_rules" in stmt:
            alert_rules_stmt = stmt
            break
    assert alert_rules_stmt is not None, "alert_rules table not found in DuckDB schema"
    assert "trigger_type" in alert_rules_stmt
    assert "trend_window_days" in alert_rules_stmt
    assert "trend_threshold" in alert_rules_stmt
    # Default value
    assert "threshold" in alert_rules_stmt

    # DuckDB must have CHECK constraint on trigger_type (Security H1 fix)
    assert "CHECK" in alert_rules_stmt.upper(), (
        "DuckDB alert_rules missing CHECK constraint — project convention "
        "requires VARCHAR+CHECK for DuckDB (no ENUM support)"
    )
    assert "trend_spike" in alert_rules_stmt
    assert "trend_drop" in alert_rules_stmt
    assert "sentiment_shift" in alert_rules_stmt

    # DuckDB must have composite CHECK for trend fields (Architecture M1 parity)
    assert "trend_window_days IS NOT NULL" in alert_rules_stmt


def test_duckdb_schema_upgrade_path_for_alert_rules() -> None:
    """DuckDB _upgrade_schema must add 3 columns to pre-existing alert_rules.

    Performance review HIGH: pre-existing DuckDB files won't get new columns
    via CREATE TABLE IF NOT EXISTS. _upgrade_schema must ALTER TABLE.
    """
    import inspect

    from core.db import duckdb_schema

    source = inspect.getsource(duckdb_schema._upgrade_schema)
    # Must check for trigger_type column existence
    assert "alert_rules" in source
    assert "trigger_type" in source
    # Must ALTER TABLE ADD COLUMN for all 3 new columns
    assert "ALTER TABLE alert_rules ADD COLUMN trigger_type" in source
    assert "ALTER TABLE alert_rules ADD COLUMN trend_window_days" in source
    assert "ALTER TABLE alert_rules ADD COLUMN trend_threshold" in source


def test_migration_28_downgrade_order_delete_before_drop() -> None:
    """Downgrade must DELETE trend rules BEFORE dropping trigger_type column.

    Architecture review M3: test must verify operation order, not just
    presence. If DROP COLUMN runs before DELETE, the DELETE fails because
    trigger_type column no longer exists.
    """
    from alembic.command import downgrade as alembic_downgrade
    from alembic.config import Config

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql://nouser:nopass@localhost:15432/nodb")
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "src" / "alembic"))

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        alembic_downgrade(
            alembic_cfg,
            "28_extend_alert_rules_for_trend:27_create_llm_compare_hourly",
            sql=True,
        )
    finally:
        sys.stdout = old_stdout
    sql = captured.getvalue()

    # Find positions of key operations
    delete_pos = sql.find("DELETE FROM alert_rules")
    drop_column_trigger_pos = sql.find("DROP COLUMN")  # First DROP COLUMN
    # Find the specific DROP COLUMN trigger_type (last one in the sequence)
    # The SQL contains "ALTER TABLE alert_rules DROP COLUMN trigger_type"
    drop_trigger_pos = sql.lower().find("drop column trigger_type")

    assert delete_pos != -1, "DELETE FROM alert_rules not found in downgrade SQL"
    assert drop_trigger_pos != -1, "DROP COLUMN trigger_type not found in downgrade SQL"
    assert delete_pos < drop_trigger_pos, (
        f"DELETE must come before DROP COLUMN trigger_type. "
        f"DELETE at pos {delete_pos}, DROP COLUMN at pos {drop_trigger_pos}"
    )
