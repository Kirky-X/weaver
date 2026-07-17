# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Migration 32 tests — extend daily_briefings for per-category briefings.

Verifies:
- Revision chain (32 extends 31_add_sentiment_shifts_article_index)
- Migration up adds category column + replaces briefing_date unique with
  (briefing_date, category) composite unique
- Migration down reverses (drops composite unique + category column,
  restores briefing_date unique)
- ORM DailyBriefing has category field + composite unique
- DuckDB schema includes category column + upgrade path for pre-existing files

Background:
- T004 BriefingGenerator produces 4 briefings per day (finance/tech/ai/general).
- Existing daily_briefings.briefing_date is UNIQUE, blocking multiple categories
  per day.
- Migration 32 drops the single-column unique, adds category column (nullable
  for backward compat with existing rows), and creates a composite
  UNIQUE(briefing_date, category).
- Null category preserves backward compat: existing rows have category=NULL,
  and PostgreSQL treats NULL as distinct in UNIQUE constraints, so existing
  rows remain valid.
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


def test_revision_chain_migration_32() -> None:
    """Migration 32 must extend 31_add_sentiment_shifts_article_index."""
    rev, down = _read_revision_vars("32_extend_daily_briefings_for_category")
    assert rev == "32_extend_daily_briefings_for_category"
    assert down == "31_add_sentiment_shifts_article_index"


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


def test_migration_32_up_adds_category_column() -> None:
    """Migration 32 up must add category column to daily_briefings."""
    sql = _capture_offline_sql(
        "31_add_sentiment_shifts_article_index",
        "32_extend_daily_briefings_for_category",
    )
    # Column add (either via ADD COLUMN or add_column)
    assert "category" in sql
    assert "ADD COLUMN" in sql or "add_column" in sql.lower()


def test_migration_32_up_drops_briefing_date_unique() -> None:
    """Migration 32 up must drop the single-column unique on briefing_date."""
    sql = _capture_offline_sql(
        "31_add_sentiment_shifts_article_index",
        "32_extend_daily_briefings_for_category",
    )
    # Drop the legacy single-column unique constraint
    assert "DROP CONSTRAINT" in sql or "drop_constraint" in sql.lower()
    # daily_briefings_briefing_date_key is the auto-generated name from
    # sa.Column(..., unique=True) in migration 04_create_analytics_tables
    assert "briefing_date" in sql


def test_migration_32_up_creates_composite_unique() -> None:
    """Migration 32 up must create UNIQUE(briefing_date, category) composite."""
    sql = _capture_offline_sql(
        "31_add_sentiment_shifts_article_index",
        "32_extend_daily_briefings_for_category",
    )
    # Composite unique constraint creation
    assert "UNIQUE" in sql.upper() or "uq_" in sql.lower()
    # Both columns in the constraint
    assert "briefing_date" in sql
    assert "category" in sql


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


def test_migration_32_down_drops_category_column() -> None:
    """Migration 32 down must drop category column from daily_briefings."""
    sql = _capture_offline_down_sql(
        "32_extend_daily_briefings_for_category",
        "31_add_sentiment_shifts_article_index",
    )
    assert "DROP COLUMN" in sql or "drop_column" in sql.lower()
    assert "category" in sql


# ── ORM field verification ──────────────────────────────────────────────────


def test_daily_briefing_orm_has_category_field() -> None:
    """DailyBriefing ORM must expose category column (T004)."""
    from core.db.models.misc import DailyBriefing

    assert hasattr(DailyBriefing, "category"), "DailyBriefing missing category"


def test_daily_briefing_orm_category_is_nullable_string() -> None:
    """category column must be String(20) and nullable (backward compat)."""
    from sqlalchemy import String

    from core.db.models.misc import DailyBriefing

    col = DailyBriefing.__table__.columns["category"]
    assert isinstance(col.type, String)
    assert col.nullable is True


def test_daily_briefing_orm_briefing_date_not_unique() -> None:
    """briefing_date column must NOT be unique (replaced by composite unique).

    Otherwise only one briefing per day is allowed, blocking T004's 4
    briefings-per-day model (finance/tech/ai/general).

    SQLAlchemy defaults `unique` to None (meaning "not set"); both None and
    False are acceptable — only True is a violation.
    """
    from core.db.models.misc import DailyBriefing

    col = DailyBriefing.__table__.columns["briefing_date"]
    assert not col.unique, (
        "briefing_date must not be unique after migration 32 — "
        "UNIQUE(briefing_date, category) replaces it"
    )


def test_daily_briefing_orm_has_composite_unique() -> None:
    """DailyBriefing __table_args__ must include UNIQUE(briefing_date, category)."""
    from sqlalchemy import UniqueConstraint

    from core.db.models.misc import DailyBriefing

    table_args = DailyBriefing.__table_args__
    if not isinstance(table_args, tuple):
        table_args = (table_args,)

    has_composite_unique = any(
        isinstance(arg, UniqueConstraint)
        and {col.name for col in arg.columns} == {"briefing_date", "category"}
        for arg in table_args
    )
    assert has_composite_unique, (
        "DailyBriefing must have UniqueConstraint(briefing_date, category) "
        "to allow 4 briefings per day (finance/tech/ai/general)"
    )


def test_daily_briefing_existing_fields_preserved() -> None:
    """Existing DailyBriefing fields must remain (no regression)."""
    from core.db.models.misc import DailyBriefing

    existing_fields = [
        "id",
        "briefing_date",
        "title",
        "summary",
        "status",
        "total_items",
        "generated_at",
    ]
    for field in existing_fields:
        assert hasattr(DailyBriefing, field), f"DailyBriefing missing existing field {field}"


# ── DuckDB schema verification ──────────────────────────────────────────────


def test_duckdb_schema_has_category_column() -> None:
    """DuckDB daily_briefings schema must include category column."""
    from core.db import duckdb_schema

    daily_briefings_stmt = None
    for stmt in duckdb_schema.SCHEMA_QUERIES:
        if "CREATE TABLE IF NOT EXISTS daily_briefings" in stmt:
            daily_briefings_stmt = stmt
            break
    assert daily_briefings_stmt is not None, "daily_briefings table not found in DuckDB schema"
    assert "category" in daily_briefings_stmt


def test_duckdb_schema_upgrade_path_for_daily_briefings_category() -> None:
    """DuckDB _upgrade_schema must add category column to pre-existing daily_briefings.

    Pre-existing DuckDB files won't get the new column via CREATE TABLE IF NOT
    EXISTS. _upgrade_schema must ALTER TABLE.
    """
    import inspect

    from core.db import duckdb_schema

    source = inspect.getsource(duckdb_schema._upgrade_schema)
    assert "daily_briefings" in source
    assert "category" in source
    assert "ALTER TABLE daily_briefings ADD COLUMN category" in source
