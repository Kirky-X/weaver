# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Migration tests — verify revision chain and upgrade/downgrade via offline SQL."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ALEMBIC_VERSIONS = (
    Path(__file__).resolve().parent.parent.parent.parent / "src" / "alembic" / "versions"
)

# ── Migration revision chain ────────────────────────────────────────────────

EXPECTED_CHAIN: list[tuple[str, str | None]] = [
    ("01_initial", None),
    ("02_refactor_persist_status", "01_initial"),
    ("03_extend_articles_fields", "02_refactor_persist_status"),
    ("04_create_analytics_tables", "03_extend_articles_fields"),
    ("05_create_security_tables", "04_create_analytics_tables"),
]


def _read_revision_vars(file_stem: str) -> tuple[str, str | None]:
    """Read revision and down_revision from a migration file without importing it."""
    import re

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


@pytest.mark.parametrize("revision_id,expected_down", EXPECTED_CHAIN)
def test_revision_chain(revision_id: str, expected_down: str | None) -> None:
    rev, down = _read_revision_vars(revision_id)
    assert rev == revision_id
    assert down == expected_down


# ── Offline Alembic generation test ─────────────────────────────────────────


def test_alembic_offline_sql_generation(tmp_path: Path) -> None:
    """Run offline migration and verify SQL output for all 3 new migrations."""
    from alembic.command import upgrade as alembic_upgrade
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    alembic_cfg = Config(str(repo_root / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", "postgresql://nouser:nopass@localhost:15432/nodb")
    alembic_cfg.set_main_option("script_location", str(repo_root / "src" / "alembic"))

    import io

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        alembic_upgrade(
            alembic_cfg, "02_refactor_persist_status:05_create_security_tables", sql=True
        )
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    assert "03_extend_articles_fields" in output
    assert "04_create_analytics_tables" in output
    assert "05_create_security_tables" in output
    assert "sentiment_shifts" in output
    assert "audit_log" in output
    assert "community_vectors" in output
