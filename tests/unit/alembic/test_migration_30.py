# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Migration 30 tests — extend sentiment_shifts for article-level tracking.

Verifies:
- Revision chain (30 extends 29_seed_default_alert_rules)
- Migration up adds 3 columns (article_id, entity_name, shift_value)
- Migration down removes 3 columns
- ORM SentimentShift has new fields with correct types
- DuckDB schema includes new columns
- DuckDB _upgrade_schema has ALTER TABLE for pre-existing files
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


def test_revision_chain_migration_30() -> None:
    """Migration 30 must extend 29_seed_default_alert_rules."""
    rev, down = _read_revision_vars("30_extend_sentiment_shifts_for_article_tracking")
    assert rev == "30_extend_sentiment_shifts_for_article_tracking"
    assert down == "29_seed_default_alert_rules"


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


def test_migration_30_up_adds_three_columns() -> None:
    """Migration 30 up must add article_id, entity_name, shift_value columns."""
    sql = _capture_offline_sql(
        "29_seed_default_alert_rules", "30_extend_sentiment_shifts_for_article_tracking"
    )

    # 3 new columns added
    assert "ADD COLUMN" in sql or "add_column" in sql.lower()
    assert "article_id" in sql
    assert "entity_name" in sql
    assert "shift_value" in sql


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


def test_migration_30_down_removes_three_columns() -> None:
    """Migration 30 down must remove article_id, entity_name, shift_value."""
    sql = _capture_offline_down_sql(
        "30_extend_sentiment_shifts_for_article_tracking", "29_seed_default_alert_rules"
    )

    # Drop 3 columns
    assert "DROP COLUMN" in sql or "drop_column" in sql.lower()
    assert "article_id" in sql
    assert "entity_name" in sql
    assert "shift_value" in sql


# ── ORM field verification ──────────────────────────────────────────────────


def test_sentiment_shift_orm_has_new_fields() -> None:
    """SentimentShift ORM must expose article_id, entity_name, shift_value."""
    from core.db.models.misc import SentimentShift

    assert hasattr(SentimentShift, "article_id"), "SentimentShift missing article_id"
    assert hasattr(SentimentShift, "entity_name"), "SentimentShift missing entity_name"
    assert hasattr(SentimentShift, "shift_value"), "SentimentShift missing shift_value"


def test_sentiment_shift_orm_field_types() -> None:
    """SentimentShift new fields must have correct types (all nullable)."""
    from sqlalchemy import Numeric, String
    from sqlalchemy.dialects.postgresql import UUID

    from core.db.models.misc import SentimentShift

    # article_id: UUID, nullable
    article_col = SentimentShift.__table__.columns["article_id"]
    assert isinstance(article_col.type, UUID)
    assert article_col.nullable is True

    # entity_name: String, nullable
    entity_col = SentimentShift.__table__.columns["entity_name"]
    assert isinstance(entity_col.type, String)
    assert entity_col.nullable is True

    # shift_value: Numeric, nullable
    shift_col = SentimentShift.__table__.columns["shift_value"]
    assert isinstance(shift_col.type, Numeric)
    assert shift_col.nullable is True


def test_sentiment_shift_existing_fields_preserved() -> None:
    """Existing SentimentShift fields must remain unchanged (no regression)."""
    from core.db.models.misc import SentimentShift

    # Existing fields must still exist
    existing_fields = [
        "id",
        "community_id",
        "community_title",
        "shift_type",
        "direction",
        "magnitude",
        "confidence",
        "detected_at",
        "window_start",
        "window_end",
        "before_avg",
        "after_avg",
        "trigger_article_ids",
        "created_at",
    ]
    for field in existing_fields:
        assert hasattr(SentimentShift, field), f"SentimentShift missing existing field {field}"


# ── DuckDB schema verification ──────────────────────────────────────────────


def test_duckdb_schema_has_new_sentiment_shifts_columns() -> None:
    """DuckDB sentiment_shifts schema must include 3 new columns."""
    from core.db import duckdb_schema

    sentiment_shifts_stmt = None
    for stmt in duckdb_schema.SCHEMA_QUERIES:
        if "CREATE TABLE IF NOT EXISTS sentiment_shifts" in stmt:
            sentiment_shifts_stmt = stmt
            break
    assert sentiment_shifts_stmt is not None, "sentiment_shifts table not found in DuckDB schema"
    assert "article_id" in sentiment_shifts_stmt
    assert "entity_name" in sentiment_shifts_stmt
    assert "shift_value" in sentiment_shifts_stmt


def test_duckdb_schema_upgrade_path_for_sentiment_shifts() -> None:
    """DuckDB _upgrade_schema must add 3 columns to pre-existing sentiment_shifts.

    Pre-existing DuckDB files won't get new columns via CREATE TABLE IF NOT
    EXISTS. _upgrade_schema must ALTER TABLE.
    """
    import inspect

    from core.db import duckdb_schema

    source = inspect.getsource(duckdb_schema._upgrade_schema)
    assert "sentiment_shifts" in source
    assert "article_id" in source
    assert "ALTER TABLE sentiment_shifts ADD COLUMN article_id" in source
    assert "ALTER TABLE sentiment_shifts ADD COLUMN entity_name" in source
    assert "ALTER TABLE sentiment_shifts ADD COLUMN shift_value" in source
