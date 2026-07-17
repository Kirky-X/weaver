# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Migration 31 tests — add covering index for article-level shift lookup.

Verifies:
- Revision chain (31 extends 30_extend_sentiment_shifts_for_article_tracking)
- Migration up creates partial composite index on (entity_name, article_id, detected_at)
- Migration down drops the index
- ORM SentimentShift.__table_args__ includes the new index
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


def test_revision_chain_migration_31() -> None:
    """Migration 31 must extend 30_extend_sentiment_shifts_for_article_tracking."""
    rev, down = _read_revision_vars("31_add_sentiment_shifts_article_index")
    assert rev == "31_add_sentiment_shifts_article_index"
    assert down == "30_extend_sentiment_shifts_for_article_tracking"


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


def test_migration_31_up_creates_index() -> None:
    """Migration 31 up must create idx_shifts_entity_article_detected."""
    sql = _capture_offline_sql(
        "30_extend_sentiment_shifts_for_article_tracking",
        "31_add_sentiment_shifts_article_index",
    )

    # Index creation
    assert "CREATE INDEX" in sql.upper()
    assert "idx_shifts_entity_article_detected" in sql
    # Partial index (Postgres-specific WHERE clause)
    assert "article_id IS NOT NULL" in sql
    # Composite index columns
    assert "entity_name" in sql
    assert "detected_at" in sql


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


def test_migration_31_down_drops_index() -> None:
    """Migration 31 down must drop idx_shifts_entity_article_detected."""
    sql = _capture_offline_down_sql(
        "31_add_sentiment_shifts_article_index",
        "30_extend_sentiment_shifts_for_article_tracking",
    )

    assert "DROP INDEX" in sql.upper()
    assert "idx_shifts_entity_article_detected" in sql


# ── ORM index verification ──────────────────────────────────────────────────


def test_sentiment_shift_orm_has_article_index() -> None:
    """SentimentShift ORM __table_args__ must include the new index."""
    from core.db.models.misc import SentimentShift

    index_names = {idx.name for idx in SentimentShift.__table_args__ if hasattr(idx, "name")}
    assert "idx_shifts_entity_article_detected" in index_names


def test_sentiment_shift_orm_index_is_partial() -> None:
    """The new ORM index must be a partial index (WHERE article_id IS NOT NULL).

    Partial index keeps it small — only article-level rows (T003) are
    indexed, community-level rows (SentimentShiftDetector) are excluded.
    """
    from core.db.models.misc import SentimentShift

    for idx in SentimentShift.__table_args__:
        if hasattr(idx, "name") and idx.name == "idx_shifts_entity_article_detected":
            # postgresql_where is stored in dialect_options
            pg_where = idx.dialect_options.get("postgresql", {}).get("where")
            assert pg_where is not None, "Index must have postgresql_where clause"
            assert "article_id IS NOT NULL" in str(pg_where)
            return
    pytest.fail("idx_shifts_entity_article_detected not found in SentimentShift __table_args__")
