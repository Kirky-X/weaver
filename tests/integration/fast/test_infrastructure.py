# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T001 验证：DB 组合 fixture 工厂 + marker 注册。"""

import pytest


@pytest.mark.db_combo
def test_db_combo_marker_registered():
    """db_combo marker 可被 --strict-markers 识别。"""
    assert True


def test_db_combos_constant():
    """DB_COMBOS 包含 4 套组合。"""
    from tests.integration.conftest import DB_COMBOS

    assert len(DB_COMBOS) == 4
    assert set(DB_COMBOS.keys()) == {
        "pg_ladybug",
        "duckdb_neo4j",
        "pg_neo4j",
        "duckdb_ladybug",
    }


@pytest.mark.bing_live
def test_bing_live_marker_registered():
    """bing_live marker 可被 --strict-markers 识别。"""
    assert True


@pytest.mark.db_failover
def test_db_failover_marker_registered():
    """db_failover marker 可被 --strict-markers 识别。"""
    assert True


@pytest.mark.slow
def test_slow_marker_registered():
    """slow marker 可被 --strict-markers 识别。"""
    assert True
