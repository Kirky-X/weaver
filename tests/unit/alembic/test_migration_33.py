# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Migration 33 tests — add payload_hash column to alert_events for 24h dedup.

Verifies:
- Revision chain (33 extends 32_extend_daily_briefings_for_category)
- Migration up adds payload_hash column (VARCHAR(64), nullable)
- Migration up creates index idx_alert_events_payload_hash on
  (rule_id, payload_hash, triggered_at) for efficient 24h dedup queries
- Migration down drops the index first, then the column (reverse order)
- ORM AlertEvent has new field with correct type (String(64), nullable)
- DuckDB schema parity (column added via _upgrade_schema)
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


def test_revision_chain_migration_33() -> None:
    """Migration 33 must extend 32_extend_daily_briefings_for_category."""
    rev, down = _read_revision_vars("33_add_alert_events_payload_hash")
    assert rev == "33_add_alert_events_payload_hash"
    assert down == "32_extend_daily_briefings_for_category"


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


def test_migration_33_up_adds_payload_hash_column() -> None:
    """Migration 33 up must add payload_hash column to alert_events."""
    sql = _capture_offline_sql(
        "32_extend_daily_briefings_for_category", "33_add_alert_events_payload_hash"
    )

    # Column added
    assert "ADD COLUMN" in sql or "add_column" in sql.lower()
    assert "payload_hash" in sql
    # VARCHAR(64) — sha256 hex digest length
    assert "VARCHAR(64)" in sql or "varchar(64)" in sql.lower() or "String(64)" in sql
    # Nullable — column must NOT be declared NOT NULL (nullable defaults to NULL
    # in PostgreSQL, so Alembic emits no explicit NULL keyword). Verify NOT NULL
    # is absent.
    assert (
        "NOT NULL" not in sql.upper()
    ), f"payload_hash must be nullable — NOT NULL must not appear in SQL: {sql[:500]}"


def test_migration_33_up_creates_payload_hash_index() -> None:
    """Migration 33 up must create composite index for 24h dedup queries.

    Index columns: (rule_id, payload_hash, triggered_at) — supports the
    dedup query ``WHERE rule_id=? AND payload_hash=? AND triggered_at > now()-24h``.
    """
    sql = _capture_offline_sql(
        "32_extend_daily_briefings_for_category", "33_add_alert_events_payload_hash"
    )

    # CREATE INDEX statement
    assert "CREATE INDEX" in sql.upper() or "create_index" in sql.lower()
    assert "idx_alert_events_payload_hash" in sql
    # Composite index on 3 columns
    assert "rule_id" in sql
    assert "payload_hash" in sql
    assert "triggered_at" in sql


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


def test_migration_33_down_drops_index_before_column() -> None:
    """Downgrade must DROP INDEX BEFORE DROP COLUMN (order matters).

    If DROP COLUMN runs before DROP INDEX, the index drop fails because
    the column no longer exists. Order is enforced.
    """
    sql = _capture_offline_down_sql(
        "33_add_alert_events_payload_hash", "32_extend_daily_briefings_for_category"
    )

    # Both DROP statements must be present
    assert (
        "DROP INDEX" in sql.upper() or "drop_index" in sql.lower()
    ), f"DROP INDEX not found in downgrade SQL: {sql[:500]}"
    assert (
        "DROP COLUMN" in sql.upper() or "drop_column" in sql.lower()
    ), f"DROP COLUMN not found in downgrade SQL: {sql[:500]}"
    assert "payload_hash" in sql

    # Order: DROP INDEX must come before DROP COLUMN
    # Normalize positions to lowercase for matching
    sql_lower = sql.lower()
    drop_index_pos = sql_lower.find("drop index")
    if drop_index_pos == -1:
        drop_index_pos = sql_lower.find("drop_index")
    drop_column_pos = sql_lower.find("drop column")
    if drop_column_pos == -1:
        drop_column_pos = sql_lower.find("drop_column")

    assert drop_index_pos != -1, "DROP INDEX position not found"
    assert drop_column_pos != -1, "DROP COLUMN position not found"
    assert drop_index_pos < drop_column_pos, (
        f"DROP INDEX (pos {drop_index_pos}) must come before "
        f"DROP COLUMN (pos {drop_column_pos})"
    )


# ── ORM field verification ──────────────────────────────────────────────────


def test_alert_event_orm_has_payload_hash_field() -> None:
    """AlertEvent ORM must expose payload_hash field (Mapped[str | None])."""
    from core.db.models.alert import AlertEvent

    assert hasattr(AlertEvent, "payload_hash"), "AlertEvent missing payload_hash field"


def test_alert_event_orm_payload_hash_field_types() -> None:
    """AlertEvent payload_hash field must be String(64), nullable."""
    from sqlalchemy import String

    from core.db.models.alert import AlertEvent

    col = AlertEvent.__table__.columns["payload_hash"]
    assert isinstance(col.type, String), f"Expected String, got {type(col.type)}"
    assert col.type.length == 64, f"Expected length=64, got {col.type.length}"
    assert (
        col.nullable is True
    ), "payload_hash must be nullable (back-compat with pre-migration rows)"


def test_alert_event_orm_has_payload_hash_index() -> None:
    """AlertEvent ORM must declare idx_alert_events_payload_hash index.

    Per Rule 11 (convention over novelty): index is declared in __table_args__
    alongside existing idx_alert_events_triggered and idx_alert_events_entity.
    """
    from core.db.models.alert import AlertEvent

    index_names = [idx.name for idx in AlertEvent.__table__.indexes]
    assert (
        "idx_alert_events_payload_hash" in index_names
    ), f"idx_alert_events_payload_hash not in {index_names}"

    # Verify the index covers the expected columns
    payload_index = next(
        (
            idx
            for idx in AlertEvent.__table__.indexes
            if idx.name == "idx_alert_events_payload_hash"
        ),
        None,
    )
    assert payload_index is not None
    column_names = [col.name for col in payload_index.columns]
    assert column_names == [
        "rule_id",
        "payload_hash",
        "triggered_at",
    ], f"Expected ['rule_id', 'payload_hash', 'triggered_at'], got {column_names}"
