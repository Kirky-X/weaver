# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for HIGH-finding fixes in alembic migrations.

Covers:
- migration 02 downgrade maps enriching -> neo4j_failed (not pg_done)
- migration 02 downgrade nulls non-UUID merged_source_ids before cast
-: migration 11 fails fast when audit_log.key_id has rows > 64 chars
- migration 13 dedupes daily_briefings before TIMESTAMPTZ->DATE and
  uses an explicit UTC conversion on downgrade
-: migration 01 validates HNSW_M / HNSW_EF_CONSTRUCTION ranges
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ALEMBIC_VERSIONS = (
    Path(__file__).resolve().parent.parent.parent.parent / "src" / "alembic" / "versions"
)


def _load_migration(stem: str):
    """Load a migration module by file path under a synthetic name."""
    path = ALEMBIC_VERSIONS / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_test_migration_{stem}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _mock_op(scalar_return: int = 0) -> MagicMock:
    """Build a mocked alembic op with a scripted get_bind.scalar chain."""
    op = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = scalar_return
    op.get_bind.return_value = conn
    return op


# ── / migration 02 ───────────────────────────────────────────


class TestMigration02Downgrade:
    def test_enriching_maps_to_neo4j_failed(self):
        """enriching must map to neo4j_failed, not pg_done."""
        mod = _load_migration("02_refactor_persist_status")
        op = _mock_op()
        with patch.object(mod, "op", op):
            mod.downgrade()
        sqls = [call.args[0] for call in op.execute.call_args_list if call.args]
        enriching = [s for s in sqls if "enriching" in s]
        assert any("neo4j_failed" in s for s in enriching)
        assert not any("pg_done" in s and "enriching" in s for s in sqls)

    def test_non_uuid_source_ids_nulled_before_cast(self):
        """Rows with URL values in merged_source_ids are NULLed, not cast."""
        mod = _load_migration("02_refactor_persist_status")
        op = _mock_op(scalar_return=3)  # 3 rows contain non-UUID values
        with patch.object(mod, "op", op):
            mod.downgrade()
        sqls = [call.args[0] for call in op.execute.call_args_list if call.args]
        null_update = [s for s in sqls if "merged_source_ids = NULL" in s]
        assert null_update, "expected an UPDATE nulling non-UUID rows"

    def test_no_null_update_when_all_uuid(self):
        """With zero offending rows the UPDATE is skipped entirely."""
        mod = _load_migration("02_refactor_persist_status")
        op = _mock_op(scalar_return=0)
        with patch.object(mod, "op", op):
            mod.downgrade()
        sqls = [call.args[0] for call in op.execute.call_args_list if call.args]
        assert not any("merged_source_ids = NULL" in s for s in sqls)


# ──: migration 11 ───────────────────────────────────────────────────


class TestMigration11KeyIdGuard:
    def test_raises_when_oversize_key_ids_exist(self):
        """Migration aborts with guidance when key_id rows exceed 64 chars."""
        mod = _load_migration("11_update_audit_log")
        op = _mock_op(scalar_return=7)
        with patch.object(mod, "op", op), pytest.raises(RuntimeError, match="7 row"):
            mod.upgrade()
        # Nothing was altered
        op.add_column.assert_not_called()

    def test_proceeds_when_no_oversize_key_ids(self):
        """With clean data the migration runs to completion."""
        mod = _load_migration("11_update_audit_log")
        op = _mock_op(scalar_return=0)
        with patch.object(mod, "op", op):
            mod.upgrade()
        op.add_column.assert_called_once()
        assert op.alter_column.call_count == 4


# ── migration 13 ───────────────────────────────────────────────────


class TestMigration13BriefingDate:
    def test_dedup_deletes_when_folding_would_collide(self):
        """Duplicate dates trigger a dedup DELETE before the type change."""
        mod = _load_migration("13_add_missing_columns")
        op = _mock_op(scalar_return=2)
        with patch.object(mod, "op", op):
            mod.upgrade()
        sqls = [call.args[0] for call in op.execute.call_args_list if call.args]
        assert any("DELETE FROM daily_briefings" in s for s in sqls)

    def test_no_delete_without_duplicates(self):
        """No dedup when every folded date is unique."""
        mod = _load_migration("13_add_missing_columns")
        op = _mock_op(scalar_return=0)
        with patch.object(mod, "op", op):
            mod.upgrade()
        sqls = [call.args[0] for call in op.execute.call_args_list if call.args]
        assert not any("DELETE FROM daily_briefings" in s for s in sqls)

    def test_upgrade_uses_date_cast(self):
        mod = _load_migration("13_add_missing_columns")
        op = _mock_op(scalar_return=0)
        with patch.object(mod, "op", op):
            mod.upgrade()
        alter = [
            c
            for c in op.alter_column.call_args_list
            if c.args[:2] == ("daily_briefings", "briefing_date")
        ]
        assert alter, "briefing_date alter missing"
        assert alter[0].kwargs.get("postgresql_using") == "briefing_date::date"

    def test_downgrade_pins_utc_conversion(self):
        """Downgrade DATE -> TIMESTAMPTZ uses an explicit AT TIME ZONE 'UTC'."""
        mod = _load_migration("13_add_missing_columns")
        op = _mock_op()
        with patch.object(mod, "op", op):
            mod.downgrade()
        alter = [
            c
            for c in op.alter_column.call_args_list
            if c.args[:2] == ("daily_briefings", "briefing_date")
        ]
        assert alter, "briefing_date alter missing"
        using = alter[0].kwargs.get("postgresql_using", "")
        assert "AT TIME ZONE 'UTC'" in using


# ──: migration 01 ─────────────────────────────────────────────────────


class TestMigration01HnswValidation:
    def test_rejects_out_of_range_m(self):
        mod = _load_migration("01_initial")
        op = MagicMock()
        with (
            patch.object(mod, "op", op),
            patch.dict(os_environ(), {"HNSW_M": "500", "HNSW_EF_CONSTRUCTION": "64"}),
            pytest.raises(ValueError, match="HNSW_M"),
        ):
            mod.upgrade()

    def test_rejects_out_of_range_ef_construction(self):
        mod = _load_migration("01_initial")
        op = MagicMock()
        with (
            patch.object(mod, "op", op),
            patch.dict(os_environ(), {"HNSW_M": "16", "HNSW_EF_CONSTRUCTION": "5"}),
            pytest.raises(ValueError, match="HNSW_EF_CONSTRUCTION"),
        ):
            mod.upgrade()

    def test_accepts_defaults(self):
        mod = _load_migration("01_initial")
        op = MagicMock()
        with (
            patch.object(mod, "op", op),
            patch.dict(os_environ(), {}, clear=False),
        ):
            os_environ()["HNSW_M"] = "16"
            os_environ()["HNSW_EF_CONSTRUCTION"] = "64"
            mod.upgrade()  # must not raise


def os_environ() -> dict:
    """Indirection so patch.dict target is a plain dict-like (os.environ)."""
    import os

    return os.environ
