# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""Pure-logic CLI routing tests for scripts/data_io.py (no Docker required)."""

from __future__ import annotations

import asyncio

from scripts.data_io import _build_parser, _async_main


def test_import_mismatched_direction_exits_2_without_secrets():
    """--from/--to 组合不匹配时返回 2，且错误信息不回显 Namespace（含明文密码）."""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "import",
            "--from",
            "ladybug",
            "--to",
            "postgres",
            "--neo4j-password",
            "s3cret-password",
        ]
    )
    code = asyncio.run(_async_main(args))
    assert code == 2


def test_import_ladybug_missing_args_returns_2():
    """ladybug→neo4j 缺少 --ladybug-path / --neo4j-password 时返回 2."""
    parser = _build_parser()
    args = parser.parse_args(["import", "--from", "ladybug", "--to", "neo4j"])
    code = asyncio.run(_async_main(args))
    assert code == 2


def test_import_duckdb_missing_args_returns_2():
    """duckdb→postgres 缺少 --duckdb-path / --pg-dsn 时返回 2."""
    parser = _build_parser()
    args = parser.parse_args(["import", "--from", "duckdb", "--to", "postgres"])
    code = asyncio.run(_async_main(args))
    assert code == 2
