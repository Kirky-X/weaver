#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Weaver data import/export tool.

Migrates data between primary databases (PostgreSQL + Neo4j) and fallback
databases (DuckDB + LadybugDB) for backup, verification, and consistency
checking across the dual-database failover architecture.

Subcommands:
    import  --from duckdb  --to postgres   : DuckDB → PostgreSQL
    export  --from postgres --to duckdb    : PostgreSQL → DuckDB
    export  --from neo4j    --to ladybug   : Neo4j → LadybugDB

Each command validates row counts after migration and exits non-zero on
mismatch. PG↔DuckDB export uses atomic file replacement (temp file + os.rename)
to guarantee the original file is preserved on failure.

Usage:
    uv run python scripts/data_io.py export --from postgres --to duckdb \\
        --pg-dsn 'postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver'\\
        --duckdb-path data/weaver.duckdb

    uv run python scripts/data_io.py export --from neo4j --to ladybug\\
        --neo4j-uri bolt://localhost:7687 --neo4j-user neo4j\\
        --neo4j-password weavertest --ladybug-path data/weaver_graph.ladybug

    uv run python scripts/data_io.py import --from duckdb --to postgres\\
        --duckdb-path data/weaver.duckdb\\
        --pg-dsn 'postgresql+asyncpg://postgres:weavertest@localhost:5432/weaver'
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 27 PG/DuckDB tables — order matters for FK-safe truncation/import
EXPECTED_TABLES: list[str] = [
    # Independent tables first
    "source_configs",
    "source_authorities",
    "relation_types",
    "relation_type_aliases",
    "unknown_relation_types",
    "api_keys",
    "prompt_templates",
    "alert_rules",
    "audit_log",
    # Articles (vertical split — core must come before bodies/analysis/processing)
    "articles_core",
    "article_bodies",
    "article_analysis",
    "article_processing",
    "article_versions",
    "article_vectors",
    # Entity/community vectors
    "entity_vectors",
    "community_vectors",
    # Sentiment / briefings / alerts
    "sentiment_shifts",
    "daily_briefings",
    "daily_briefing_items",
    "alert_events",
    # Sync / saga / LLM
    "pending_sync",
    "saga_logs",
    "llm_failure_records",
    "llm_usage_raw",
    "llm_usage_hourly",
    "llm_compare_hourly",
]

# 8 LadybugDB node labels (matches ladybug_schema.py SCHEMA_QUERIES)
EXPECTED_NODE_LABELS: list[str] = [
    "Entity",
    "Article",
    "Community",
    "CommunityReport",
    "EventNode",
    "NarrativeNode",
    "SchemaNode",
    "_CommunityMetadata",
]

# 13 LadybugDB relationship types (matches ladybug_schema.py SCHEMA_QUERIES)
EXPECTED_REL_TYPES: list[str] = [
    "MENTIONS",
    "FOLLOWED_BY",
    "EVENT_FOLLOWED_BY",
    "CAUSES",
    "ENABLES",
    "PREVENTS",
    "RELATED_TO",
    "HAS_ENTITY",
    "REPORTS_ON",
    "HAS_PARTICIPANT",
    "HAS_SUB_EVENT",
    "HAS_NARRATIVE",
    "HAS_EVENT",
]

# Schema definition imports — re-exported from src for schema initialization
# Lazy import inside functions to avoid loading full src/ when running --help.

# Batch size for INSERT operations
BATCH_SIZE = 1000


def _ensure_src_path() -> None:
    """Insert src/ into sys.path for lazy imports of core.db.* modules.

    Consolidates the 4 repeated ``sys.path.insert`` blocks that previously
    appeared inside individual functions. Idempotent: safe to call multiple
    times.
    """
    import sys

    src_path = str(Path(__file__).resolve().parent.parent / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


# ── Helpers ─────────────────────────────────────────────────────────


def _convert_value_for_duckdb(v: Any) -> Any:
    """Convert a PG value to a DuckDB-compatible Python value.

    - pgvector Vector → list[float]
    - numpy ndarray → list
    - datetime/date → unchanged (DuckDB handles)
    - uuid.UUID → str (DuckDB accepts UUID type but str is safer for round-trip)
    - list/tuple → list
    - other → unchanged
    """
    if v is None:
        return None
    # pgvector returns numpy.ndarray for Vector columns
    if hasattr(v, "tolist") and not isinstance(v, (list, tuple, str, bytes)):
        try:
            return list(v.tolist())
        except Exception:
            return v
    if isinstance(v, (list, tuple)):
        return list(v)
    return v


def _convert_value_for_pg(v: Any, *, is_vector: bool = False) -> Any:
    """Convert a DuckDB value to a PG-compatible asyncpg value.

    - pgvector columns (is_vector=True): list[float] → "[0.1,0.2,...]" str
      (asyncpg doesn't natively understand pgvector type without codec
      registration, which SQLAlchemy asyncpg dialect doesn't expose)
    - other list/tuple: pass through as list (asyncpg handles arrays)
    """
    if v is None:
        return None
    if is_vector and isinstance(v, (list, tuple)):
        # pgvector text format: "[0.1,0.2,...]"
        return "[" + ",".join(repr(float(x)) for x in v) + "]"
    if isinstance(v, (list, tuple)):
        return list(v)
    return v


async def _get_pg_vector_columns(pg_conn, table: str) -> set[str]:
    """Return column names of pgvector type for a PG table.

    pgvector columns have udt_name='vector' (or 'vec' for some versions).
    """
    from sqlalchemy import text

    result = await pg_conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t AND table_schema = 'public' "
            "AND udt_name IN ('vector', 'vec', 'halfvec')"
        ),
        {"t": table},
    )
    return {r[0] for r in result.fetchall()}


def _get_duckdb_columns(duck_conn, table: str) -> list[str]:
    """Return ordered column names for a DuckDB table."""
    rows = duck_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return [r[0] for r in rows]


async def _get_pg_columns(pg_conn, table: str) -> list[str]:
    """Return ordered column names for a PG table."""
    from sqlalchemy import text

    result = await pg_conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t AND table_schema = 'public' "
            "ORDER BY ordinal_position"
        ),
        {"t": table},
    )
    # SQLAlchemy AsyncConnection: execute() is async, fetchall() is sync
    return [r[0] for r in result.fetchall()]


def _get_duckdb_column_types(duck_conn, table: str) -> dict[str, str]:
    """Return {column_name: data_type} for a DuckDB table."""
    rows = duck_conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return {r[0]: r[1] for r in rows}


async def _get_pg_column_types(pg_conn, table: str) -> dict[str, str]:
    """Return {column_name: data_type} for a PG table (udt_name normalized)."""
    from sqlalchemy import text

    result = await pg_conn.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_name = :t AND table_schema = 'public' "
            "ORDER BY ordinal_position"
        ),
        {"t": table},
    )
    return {r[0]: r[1] for r in result.fetchall()}


# Type pairs that are fundamentally incompatible (cannot auto-convert).
# PK columns with these mismatches would silently corrupt data, so we
# skip the entire table and print a warning.
_INCOMPATIBLE_TYPE_PAIRS: dict[str, set[str]] = {
    "uuid": {"int8", "bigint", "int4", "integer", "int2", "smallint"},
    "int8": {"uuid"},
    "int4": {"uuid"},
}


def _is_pk_type_incompatible(duck_type: str, pg_type: str) -> bool:
    """Return True if DuckDB and PG PK types are fundamentally incompatible."""
    d = duck_type.lower()
    p = pg_type.lower()
    return p in _INCOMPATIBLE_TYPE_PAIRS.get(d, set())


def _init_duckdb_schema(duck_conn) -> None:
    """Initialize DuckDB schema (sequences + tables + views).

    Reuses schema definitions from src/core/db/duckdb_schema.py to guarantee
    parity with the application's normal schema initialization.
    """
    _ensure_src_path()

    from core.db.duckdb_schema import (
        SCHEMA_QUERIES,
        SEQUENCE_QUERIES,
        VIEW_QUERIES,
    )

    for q in SEQUENCE_QUERIES:
        duck_conn.execute(q)
    for q in SCHEMA_QUERIES:
        duck_conn.execute(q)
    for q in VIEW_QUERIES:
        # View may already exist or have dependency issues
        with contextlib.suppress(Exception):
            duck_conn.execute(q)


def _init_ladybug_schema(ladybug_conn) -> None:
    """Initialize LadybugDB schema (8 nodes + 13 relationships).

    Reuses schema definitions from src/core/db/ladybug_schema.py to guarantee
    parity with the application's normal schema initialization.
    """
    _ensure_src_path()

    from core.db.ladybug_schema import SCHEMA_QUERIES

    for q in SCHEMA_QUERIES:
        # ALTER TABLE ADD COLUMN will fail if column exists; CREATE NODE
        # TABLE IF NOT EXISTS is idempotent. Both are safe to ignore.
        with contextlib.suppress(Exception):
            ladybug_conn.execute(q)


def _to_epoch_seconds(v: Any) -> int | None:
    """Convert a Neo4j datetime / Python datetime to INT64 epoch seconds."""
    if v is None:
        return None
    if hasattr(v, "to_native"):  # neo4j.time.DateTime
        v = v.to_native()
    if isinstance(v, datetime):
        return int(v.timestamp())
    if isinstance(v, (int, float)):
        return int(v)
    return None


def _convert_neo4j_node_props(props: dict, ladybug_cols: list[str]) -> dict:
    """Convert Neo4j node properties to LadybugDB-compatible dict.

    LadybugDB schema uses INT64 for timestamps; Neo4j uses datetime.
    Only properties whose keys match LadybugDB columns are kept.

    ID fallback: some Neo4j labels (e.g., Article) use ``pg_id`` as the
    business key and lack an explicit ``id`` property. When ``id`` is a
    LadybugDB column but missing from ``props``, fall back to
    ``pg_id`` / ``entity_id`` / ``community_id`` to satisfy the
    non-null PRIMARY KEY constraint.
    """
    out: dict = {}
    for col in ladybug_cols:
        if col in props:
            v = props[col]
            # ID fallback: Neo4j may return None for missing `id` property
            # (e.g., Article label uses `pg_id` as business key). Use a
            # sibling key to satisfy the non-null PRIMARY KEY constraint.
            if col == "id" and v is None:
                for fallback_key in ("pg_id", "entity_id", "community_id"):
                    fv = props.get(fallback_key)
                    if fv is not None:
                        out[col] = fv
                        break
                else:
                    out[col] = None
                continue
            # Heuristic: columns named *_at / *_time / publish_time are INT64 timestamps
            if col.endswith("_at") or col.endswith("_time"):
                out[col] = _to_epoch_seconds(v)
            else:
                out[col] = v
        elif col == "id":
            # Fallback: use a sibling business key as the LadybugDB PK
            for fallback_key in ("pg_id", "entity_id", "community_id"):
                if fallback_key in props:
                    out[col] = props[fallback_key]
                    break
        # else: leave missing; LadybugDB will use default or NULL
    return out


# ── Migration functions ─────────────────────────────────────────────


def _reset_duckdb_sequences(duck_conn) -> None:
    """Reset all BIGINT PK sequences to MAX(id) + 1.

    PG→DuckDB data import copies id values from PG, but DuckDB sequences
    remain at their initial START value (1). Without reset, the next
    INSERT via nextval() returns id=1, which collides with imported rows
    (F-007: ``Duplicate key 'id: N' violates primary key constraint``).

    For each BIGINT PK table:
      1. ``SELECT MAX(id)`` to find the largest id.
      2. ``ALTER TABLE ... ALTER COLUMN id DROP DEFAULT`` to break the
         sequence dependency (DuckDB rejects ``DROP SEQUENCE`` while a
         column DEFAULT references it).
      3. ``DROP SEQUENCE`` + ``CREATE SEQUENCE ... START <max_id + 1>``.
      4. ``ALTER TABLE ... ALTER COLUMN id SET DEFAULT nextval(...)`` to
         restore the column default.

    Tables with no rows get START 1 (idempotent).

    DuckDB limitations worked around:
      - ``ALTER SEQUENCE ... RESTART WITH`` is "Not implemented" in
        DuckDB ≤1.5.x, so we must DROP+CREATE the sequence.
      - ``DROP SEQUENCE ... CASCADE`` would also drop the dependent
        table (data loss), so we break the dependency via DROP DEFAULT
        first.

    Rule 12 (failures must be explicit): any failure is collected and
    raised at the end so the script exits non-zero and the user sees
    every failing sequence in one run.
    """
    _ensure_src_path()
    from core.db.duckdb_schema import BIGINT_PK_TABLES

    failed_sequences: list[tuple[str, str]] = []
    for table, seq_name in BIGINT_PK_TABLES.items():
        try:
            # table/seq_name from BIGINT_PK_TABLES hardcoded constant
            # (core/db/duckdb_schema.py), next_id is int(max_id)+1. No user
            # input surface; same risk class as scripts/db.py (accepted in
            # CLAUDE.md Security Audit).
            row = duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                f'SELECT MAX(id) FROM "{table}"'
            ).fetchone()
            max_id = row[0] if row and row[0] is not None else 0
            next_id = max_id + 1
            # Break the column DEFAULT → sequence dependency so DROP
            # SEQUENCE succeeds without CASCADE (CASCADE would also
            # drop the table, losing the data we just imported).
            duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                f'ALTER TABLE "{table}" ALTER COLUMN id DROP DEFAULT'
            )
            duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                f"DROP SEQUENCE IF EXISTS {seq_name}"
            )
            duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                f"CREATE SEQUENCE {seq_name} START {next_id}"
            )
            # Restore the DEFAULT nextval() so future INSERTs auto-increment.
            duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                f"ALTER TABLE \"{table}\" ALTER COLUMN id SET DEFAULT nextval('{seq_name}')"
            )
        except Exception as exc:
            # Collect failures; raise after attempting all sequences
            # so the user sees every problem in one run (Rule 12).
            failed_sequences.append((seq_name, str(exc)))

    if failed_sequences:
        details = "; ".join(f"{s}: {r}" for s, r in failed_sequences)
        raise RuntimeError(f"Sequence reset failed for {len(failed_sequences)} table(s): {details}")


async def export_postgres_to_duckdb(pg_dsn: str, duckdb_path: str) -> None:
    """Export all 27 tables from PostgreSQL to a DuckDB file.

    Atomicity: writes to ``duckdb_path + ".tmp"`` first, then ``os.replace()``
    to the final path only after all tables are verified. On failure, the
    temporary file is deleted and the original file (if any) is preserved.

    Snapshot consistency: all 27 table reads run inside a single
    ``REPEATABLE READ`` transaction so concurrent writes cannot cause
    inter-table row count drift (Bug 3). The snapshot is established at
    the first SELECT; every subsequent SELECT sees the same view.
    """
    import duckdb
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    tmp_path = duckdb_path + ".tmp"
    # Clean up any stale tmp file from previous failed run
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    # Make parent dir exist
    Path(duckdb_path).parent.mkdir(parents=True, exist_ok=True)

    # Bug 3: set REPEATABLE READ isolation at engine creation so every
    # connection from this engine uses a single snapshot for all reads.
    # This engine is used only for this export, so setting the default
    # isolation level is safe. SQLAlchemy autobegin keeps all SELECTs in
    # one transaction; the snapshot is established at the first SELECT,
    # so every table sees the same data view even under concurrent writes.
    engine = create_async_engine(
        pg_dsn,
        pool_pre_ping=True,
        isolation_level="REPEATABLE READ",
    )
    duck_conn = duckdb.connect(tmp_path, read_only=False)
    try:
        # 1. Initialize DuckDB schema
        _init_duckdb_schema(duck_conn)

        # 2. Export each table. All SELECTs below run inside the
        #    autobegin transaction with REPEATABLE READ isolation
        #    (snapshot established at the first statement).
        async with engine.connect() as pg_conn:
            for table in EXPECTED_TABLES:
                duck_cols = _get_duckdb_columns(duck_conn, table)
                if not duck_cols:
                    raise RuntimeError(f"Table {table} not found in DuckDB schema")
                pg_cols = await _get_pg_columns(pg_conn, table)
                if not pg_cols:
                    raise RuntimeError(f"Table {table} not found in PG schema")

                # Use intersection in DuckDB column order
                common_cols = [c for c in duck_cols if c in pg_cols]
                if not common_cols:
                    raise RuntimeError(f"No common columns for table {table}")

                col_str = ",".join(f'"{c}"' for c in common_cols)
                result = await pg_conn.execute(
                    text(f'SELECT {col_str} FROM "{table}"')  # nosemgrep: avoid-sqlalchemy-text
                )
                # SQLAlchemy AsyncConnection.execute() returns CursorResult;
                # fetchall() is synchronous.
                rows = result.fetchall()

                if not rows:
                    continue

                # Convert values for DuckDB
                converted_rows = [[_convert_value_for_duckdb(v) for v in row] for row in rows]

                # Batch INSERT
                placeholders = ",".join(["?"] * len(common_cols))
                insert_sql = f'INSERT INTO "{table}" ({col_str}) VALUES ({placeholders})'
                duck_conn.executemany(insert_sql, converted_rows)

                # Verify row count
                pg_count = len(rows)
                count_row = duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()
                assert count_row is not None, f"DuckDB COUNT returned None for {table}"
                duck_count = count_row[0]
                if pg_count != duck_count:
                    raise RuntimeError(
                        f"Row count mismatch for {table}: PG={pg_count}, DuckDB={duck_count}"
                    )

        # 3. Reset BIGINT PK sequences to MAX(id) + 1
        # PG→DuckDB data import copies id values from PG, but DuckDB
        # sequences remain at START 1. Without reset, next INSERT via
        # nextval() returns id=1 → PK conflict (F-007).
        _reset_duckdb_sequences(duck_conn)

        # 4. Atomic replace — only after all tables verified
        duck_conn.close()
        duck_conn = None  # type: ignore[assignment]
        # On Windows, os.replace works across same volume; on Linux it's atomic
        os.replace(tmp_path, duckdb_path)
    except Exception:
        # Clean up tmp on failure — preserve original file
        with contextlib.suppress(Exception):
            if duck_conn is not None:
                duck_conn.close()
        if os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.remove(tmp_path)
        raise
    finally:
        await engine.dispose()


async def import_duckdb_to_postgres(duckdb_path: str, pg_dsn: str) -> None:
    """Import all 27 tables from a DuckDB file into PostgreSQL.

    Strategy:
        1. TRUNCATE all 27 PG tables (RESTART IDENTITY CASCADE) in FK-safe order
        2. For each table in EXPECTED_TABLES order (FK-friendly), read from
           DuckDB and batch INSERT into PG
        3. Reset BIGINT PK sequences to MAX(id) + 1
        4. Verify row counts match
    """
    import duckdb
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    # BIGINT_PK_TABLES is needed for sequence reset (phase 3). It is
    # imported here rather than at module top to keep --help fast (the
    # src/ package is heavy to load).
    _ensure_src_path()
    from core.db.duckdb_schema import BIGINT_PK_TABLES

    if not os.path.exists(duckdb_path):
        raise FileNotFoundError(f"DuckDB file not found: {duckdb_path}")

    engine = create_async_engine(pg_dsn, pool_pre_ping=True)
    duck_conn = duckdb.connect(duckdb_path, read_only=True)
    try:
        # 1. TRUNCATE all PG tables (RESTART IDENTITY CASCADE)
        # EXPECTED_TABLES is in FK-friendly order (parents first); for
        # TRUNCATE we use CASCADE so order doesn't matter, but we still
        # iterate in reverse to be safe with any non-CASCADE FKs.
        async with engine.begin() as pg_conn:
            for table in reversed(EXPECTED_TABLES):
                await pg_conn.execute(
                    text(
                        f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE'
                    )  # nosemgrep: avoid-sqlalchemy-text
                )

        # Track skipped tables due to incompatible schema drift
        skipped_tables: list[tuple[str, str]] = []

        # 2. Import each table
        async with engine.begin() as pg_conn:
            for table in EXPECTED_TABLES:
                duck_cols = _get_duckdb_columns(duck_conn, table)
                if not duck_cols:
                    raise RuntimeError(f"Table {table} not found in DuckDB schema")
                pg_cols = await _get_pg_columns(pg_conn, table)
                if not pg_cols:
                    raise RuntimeError(f"Table {table} not found in PG schema")

                # Use intersection in PG column order — DuckDB may have
                # extra columns (e.g., relation_types.usage_count) that PG
                # doesn't have, and vice versa.
                common_cols = [c for c in pg_cols if c in duck_cols]
                if not common_cols:
                    raise RuntimeError(f"No common columns for table {table}")

                # Schema drift check: if PK column has fundamentally
                # incompatible types (e.g., DuckDB id=UUID vs PG id=BIGINT
                # from older schema), skip the table rather than corrupt
                # the data. This handles imports from DuckDB files created
                # before schema drift fixes (see git log for llm_usage_raw).
                if "id" in common_cols:
                    duck_types = _get_duckdb_column_types(duck_conn, table)
                    pg_types = await _get_pg_column_types(pg_conn, table)
                    duck_id_type = duck_types.get("id", "")
                    pg_id_type = pg_types.get("id", "")
                    if _is_pk_type_incompatible(duck_id_type, pg_id_type):
                        reason = f"id type incompatible: DuckDB={duck_id_type}, PG={pg_id_type}"
                        skipped_tables.append((table, reason))
                        print(
                            f"  WARN: skipping {table} — {reason}",
                            file=sys.stderr,
                        )
                        continue

                # Read all rows from DuckDB (only common columns)
                col_str = ",".join(f'"{c}"' for c in common_cols)
                rows = duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                    f'SELECT {col_str} FROM "{table}"'
                ).fetchall()

                if not rows:
                    continue

                # Identify pgvector columns for this table (need string format
                # for asyncpg, which doesn't natively understand pgvector)
                vector_cols = await _get_pg_vector_columns(pg_conn, table)

                # Convert values for PG (asyncpg)
                converted_rows = [
                    [
                        _convert_value_for_pg(v, is_vector=(col in vector_cols))
                        for v, col in zip(row, common_cols, strict=True)
                    ]
                    for row in rows
                ]

                # Batch INSERT with named placeholders
                # Use asyncpg-style $1, $2, ... via SQLAlchemy text()
                col_list_str = ",".join(f'"{c}"' for c in common_cols)
                param_list_str = ",".join(f":p{i}" for i in range(len(common_cols)))
                insert_sql = f'INSERT INTO "{table}" ({col_list_str}) VALUES ({param_list_str})'

                # Build batch params (list of dicts)
                for batch_start in range(0, len(converted_rows), BATCH_SIZE):
                    batch = converted_rows[batch_start : batch_start + BATCH_SIZE]
                    params_batch = [
                        {f"p{i}": row[i] for i in range(len(common_cols))} for row in batch
                    ]
                    await pg_conn.execute(
                        text(insert_sql),  # nosemgrep: avoid-sqlalchemy-text
                        params_batch,
                    )

                # Verify row count
                duck_count = len(rows)
                pg_count = (
                    await pg_conn.execute(
                        text(f'SELECT COUNT(*) FROM "{table}"')  # nosemgrep: avoid-sqlalchemy-text
                    )
                ).scalar()
                if pg_count != duck_count:
                    raise RuntimeError(
                        f"Row count mismatch for {table}: DuckDB={duck_count}, PG={pg_count}"
                    )

        # 3. Reset sequences for BIGINT PK tables
        async with engine.begin() as pg_conn:
            for table in BIGINT_PK_TABLES:
                # DuckDB imports preserve original id values; reset PG
                # sequence to MAX(id) + 1 so future inserts don't conflict.
                seq_name = f"{table}_id_seq"
                # Check sequence exists (some tables may have different seq names)
                seq_exists = (
                    await pg_conn.execute(
                        text("SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = :seq"),
                        {"seq": seq_name},
                    )
                ).scalar()
                if not seq_exists:
                    continue
                max_id = (
                    await pg_conn.execute(
                        text(
                            f'SELECT COALESCE(MAX(id), 0) FROM "{table}"'
                        )  # nosemgrep: avoid-sqlalchemy-text
                    )
                ).scalar()
                await pg_conn.execute(
                    text(
                        f"SELECT setval('{seq_name}', :max, true)"
                    ),  # nosemgrep: avoid-sqlalchemy-text
                    {"max": max_id if (max_id or 0) > 0 else 1},
                )

        # 4. Report skipped tables (Rule 12: skip count and reason must
        # be displayed, not buried in logs)
        if skipped_tables:
            print(
                f"\nWARNING: {len(skipped_tables)} table(s) skipped due to "
                f"incompatible schema drift:",
                file=sys.stderr,
            )
            for table, reason in skipped_tables:
                print(f"  - {table}: {reason}", file=sys.stderr)
    finally:
        duck_conn.close()
        await engine.dispose()


async def export_neo4j_to_ladybug(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    ladybug_path: str,
) -> None:
    """Export all 8 node labels and 13 relationship types from Neo4j to LadybugDB.

    Strategy:
        1. Initialize LadybugDB schema (CREATE NODE/REL TABLE IF NOT EXISTS)
        2. For each node label, fetch all nodes from Neo4j in batches of 1000
           and CREATE in LadybugDB
        3. For each relationship type, fetch all rels from Neo4j in batches
           and CREATE in LadybugDB
        4. Verify node/rel counts match between source and target

    LadybugDB compatibility constraints:
        - Use ``r.edge_type`` not ``type(r)`` to access relationship type
        - Use ``id`` property as primary key (no ``elementId()``)
        - Timestamps: Neo4j datetime → INT64 epoch seconds
    """
    import real_ladybug as ladybug
    from neo4j import GraphDatabase

    # Make parent dir exist
    Path(ladybug_path).parent.mkdir(parents=True, exist_ok=True)

    # If the target file exists, remove it — Kùzu requires a fresh
    # database file when (re)initializing schema. Appending to an
    # existing file may corrupt the catalog.
    if Path(ladybug_path).exists():
        Path(ladybug_path).unlink()

    # 1. Initialize LadybugDB — pass max_db_size/buffer_pool_size to
    # match LadybugPool's production configuration, avoiding catalog
    # corruption from size-mismatched reopen.
    ladybug_db = ladybug.Database(
        ladybug_path,
        max_db_size=1 * 1024 * 1024 * 1024,
        buffer_pool_size=256 * 1024 * 1024,
    )
    ladybug_conn = ladybug.Connection(ladybug_db)
    _init_ladybug_schema(ladybug_conn)

    # 2. Connect to Neo4j
    neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

    try:
        # 3. Export nodes for each label
        for label in EXPECTED_NODE_LABELS:
            # Get LadybugDB columns for this label
            try:
                col_result = ladybug_conn.execute("CALL SHOW_TABLES() RETURN *")
            except Exception:
                col_result = None

            # Use information_schema equivalent for kuzu/ladybug
            # LadybugDB stores node table schema in catalog; query via SHOW_COLUMNS
            ladybug_cols = _get_ladybug_node_columns(ladybug_conn, label)
            if not ladybug_cols:
                # Label not in schema (e.g., _CommunityMetadata may be skipped
                # if no data exists in Neo4j). Skip silently.
                continue

            # Count nodes in Neo4j for this label
            with neo4j_driver.session() as session:
                count_result = session.run(f"MATCH (n:`{label}`) RETURN count(n) AS cnt").single()
                neo4j_count = count_result["cnt"] if count_result else 0

                if neo4j_count == 0:
                    continue

                # Fetch all nodes in batches
                col_str = ", ".join(f"n.{c} AS {c}" for c in ladybug_cols)
                # Some labels have property names that may differ; use
                # coalesce to handle missing properties gracefully
                result = session.run(f"MATCH (n:`{label}`) RETURN {col_str}")

                batch_nodes: list[dict] = []
                for record in result:
                    props = _convert_neo4j_node_props(dict(record), ladybug_cols)
                    batch_nodes.append(props)

                    if len(batch_nodes) >= BATCH_SIZE:
                        _ladybug_create_nodes(ladybug_conn, label, ladybug_cols, batch_nodes)
                        batch_nodes = []

                if batch_nodes:
                    _ladybug_create_nodes(ladybug_conn, label, ladybug_cols, batch_nodes)

                # Verify count
                # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                ladybug_count_result = ladybug_conn.execute(  # type: ignore[union-attr]
                    f"MATCH (n:`{label}`) RETURN count(n) AS cnt"
                ).get_next()
                ladybug_count = ladybug_count_result[0]  # type: ignore[index]
                if neo4j_count != ladybug_count:
                    raise RuntimeError(
                        f"Node count mismatch for {label}: "
                        f"Neo4j={neo4j_count}, LadybugDB={ladybug_count}"
                    )

        # 4. Export relationships for each type
        for rel_type in EXPECTED_REL_TYPES:
            # Get LadybugDB rel properties (excluding FROM/TO)
            rel_props = _get_ladybug_rel_properties(ladybug_conn, rel_type)
            # Determine FROM/TO labels for this rel type
            from_label, to_label = _get_ladybug_rel_endpoints(rel_type)

            with neo4j_driver.session() as session:
                # Count rels in Neo4j
                count_result = session.run(
                    f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
                ).single()
                neo4j_count = count_result["cnt"] if count_result else 0

                if neo4j_count == 0:
                    continue

                # Fetch all rels with FROM/TO node ids
                # Use id property (not elementId) for LadybugDB compat.
                # Some labels (e.g., Article) lack an explicit `id` property
                # and use `pg_id` / `entity_id` / `community_id` as the
                # business key; coalesce to satisfy the LadybugDB PK lookup.
                prop_str = ""
                if rel_props:
                    prop_str = ", " + ", ".join(f"r.{p} AS {p}" for p in rel_props)

                result = session.run(
                    f"MATCH (a)-[r:`{rel_type}`]->(b) "
                    f"RETURN coalesce(a.id, a.pg_id, a.entity_id, a.community_id) AS _from_id, "
                    f"coalesce(b.id, b.pg_id, b.entity_id, b.community_id) AS _to_id"
                    f"{prop_str}"
                )

                batch_rels: list[dict] = []
                for record in result:
                    rel_data = dict(record)
                    batch_rels.append(rel_data)

                    if len(batch_rels) >= BATCH_SIZE:
                        _ladybug_create_rels(
                            ladybug_conn,
                            rel_type,
                            from_label,
                            to_label,
                            rel_props,
                            batch_rels,
                        )
                        batch_rels = []

                if batch_rels:
                    _ladybug_create_rels(
                        ladybug_conn,
                        rel_type,
                        from_label,
                        to_label,
                        rel_props,
                        batch_rels,
                    )

                # Verify count
                # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                ladybug_count_result = ladybug_conn.execute(  # type: ignore[union-attr]
                    f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
                ).get_next()
                ladybug_count = ladybug_count_result[0]  # type: ignore[index]
                if neo4j_count != ladybug_count:
                    raise RuntimeError(
                        f"Rel count mismatch for {rel_type}: "
                        f"Neo4j={neo4j_count}, LadybugDB={ladybug_count}"
                    )
    finally:
        neo4j_driver.close()
        # Flush and close LadybugDB connection + database to ensure all
        # writes are persisted to disk. Without explicit close, Kùzu may
        # leave the file in an inconsistent state (catalog/metadata not
        # flushed), causing "Unable to open database. The file is not a
        # valid Kuzu database file!" on subsequent open.
        with contextlib.suppress(Exception):
            ladybug_conn.close()
        with contextlib.suppress(Exception):
            ladybug_db.close()


async def validate_migration(
    *,
    source_type: str,
    target_type: str,
    source_dsn: str | None = None,
    source_path: str | None = None,
    target_dsn: str | None = None,
    target_path: str | None = None,
) -> list[dict[str, Any]]:
    """Compare row counts across all 27 tables between source and target.

    Args:
        source_type: "postgres" or "duckdb".
        target_type: "postgres" or "duckdb".
        source_dsn: PG DSN (required if source_type == "postgres").
        source_path: DuckDB file path (required if source_type == "duckdb").
        target_dsn: PG DSN (required if target_type == "postgres").
        target_path: DuckDB file path (required if target_type == "duckdb").

    Returns:
        List of dicts: ``[{"table": str, "source_count": int,
        "target_count": int, "match": bool}, ...]`` for all 27 tables.
    """
    # Validate required parameters
    if source_type == "postgres" and not source_dsn:
        raise ValueError("source_dsn required when source_type='postgres'")
    if source_type == "duckdb" and not source_path:
        raise ValueError("source_path required when source_type='duckdb'")
    if target_type == "postgres" and not target_dsn:
        raise ValueError("target_dsn required when target_type='postgres'")
    if target_type == "duckdb" and not target_path:
        raise ValueError("target_path required when target_type='duckdb'")

    source_counts = await _get_table_counts(
        db_type=source_type,
        dsn=source_dsn,
        path=source_path,
    )
    target_counts = await _get_table_counts(
        db_type=target_type,
        dsn=target_dsn,
        path=target_path,
    )

    results: list[dict[str, Any]] = []
    for table in EXPECTED_TABLES:
        s = source_counts.get(table, 0)
        t = target_counts.get(table, 0)
        results.append(
            {
                "table": table,
                "source_count": s,
                "target_count": t,
                "match": s == t,
            }
        )
    return results


async def _get_table_counts(
    *,
    db_type: str,
    dsn: str | None = None,
    path: str | None = None,
) -> dict[str, int]:
    """Get row counts for all 27 tables in a database.

    Args:
        db_type: "postgres" or "duckdb".
        dsn: PG DSN (for postgres).
        path: DuckDB file path (for duckdb).
    """
    if db_type == "postgres":
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        if not dsn:
            raise ValueError("dsn is required for postgres db_type")
        engine = create_async_engine(dsn, pool_pre_ping=True)
        try:
            counts: dict[str, int] = {}
            async with engine.connect() as conn:
                for table in EXPECTED_TABLES:
                    result = await conn.execute(
                        text(f'SELECT COUNT(*) FROM "{table}"')  # nosemgrep: avoid-sqlalchemy-text
                    )
                    counts[table] = result.scalar() or 0
            return counts
        finally:
            await engine.dispose()
    elif db_type == "duckdb":
        import duckdb

        if not path:
            raise ValueError("path is required for duckdb db_type")
        duck_conn = duckdb.connect(path, read_only=True)
        try:
            counts = {}
            for table in EXPECTED_TABLES:
                try:
                    cnt_row = duck_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                        f'SELECT COUNT(*) FROM "{table}"'
                    ).fetchone()
                    cnt = cnt_row[0] if cnt_row else 0
                    counts[table] = cnt
                except Exception:
                    # Table may not exist in DuckDB (e.g., schema not initialized)
                    counts[table] = 0
            return counts
        finally:
            duck_conn.close()
    else:
        raise ValueError(f"Unknown db_type: {db_type}")


# ── LadybugDB helpers ───────────────────────────────────────────────


def _get_ladybug_node_columns(ladybug_conn, label: str) -> list[str]:
    """Get column names for a LadybugDB node table.

    Uses ``CALL TABLE_INFO('Label') RETURN *`` which returns rows of
    ``[index, name, type, is_null, is_primary_key]``. We extract ``name``
    (row[1]).

    Falls back to ``_FALLBACK_NODE_COLUMNS`` if introspection fails.
    """
    try:
        result = (
            ladybug_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                f"CALL TABLE_INFO('{label}') RETURN *"
            )
        )
        cols: list[str] = []
        while result.has_next():
            row = result.get_next()
            # row = [index, name, type, is_null, is_primary_key]
            cols.append(row[1])
        if cols:
            return cols
    except Exception:
        pass
    return _FALLBACK_NODE_COLUMNS.get(label, [])


def _get_ladybug_rel_properties(ladybug_conn, rel_type: str) -> list[str]:
    """Get property names (excluding FROM/TO endpoints) for a rel table.

    Uses ``CALL TABLE_INFO('RelType') RETURN *``. For REL tables,
    TABLE_INFO only returns the explicit properties (FROM/TO endpoints
    are not listed as rows), so no filtering is needed.

    Falls back to ``_FALLBACK_REL_PROPS`` if introspection fails.
    """
    try:
        result = (
            ladybug_conn.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
                f"CALL TABLE_INFO('{rel_type}') RETURN *"
            )
        )
        props: list[str] = []
        while result.has_next():
            row = result.get_next()
            # row = [index, name, type, is_null, multiplicity]
            props.append(row[1])
        if props:
            return props
    except Exception:
        pass
    return _FALLBACK_REL_PROPS.get(rel_type, [])


def _get_ladybug_rel_endpoints(rel_type: str) -> tuple[str, str]:
    """Return (FROM_label, TO_label) for a rel type, per ladybug_schema.py."""
    endpoints = {
        "MENTIONS": ("Article", "Entity"),
        "FOLLOWED_BY": ("Article", "Article"),
        "EVENT_FOLLOWED_BY": ("EventNode", "EventNode"),
        "CAUSES": ("EventNode", "EventNode"),
        "ENABLES": ("EventNode", "EventNode"),
        "PREVENTS": ("EventNode", "EventNode"),
        "RELATED_TO": ("Entity", "Entity"),
        "HAS_ENTITY": ("Community", "Entity"),
        "REPORTS_ON": ("CommunityReport", "Community"),
        "HAS_PARTICIPANT": ("EventNode", "Entity"),
        "HAS_SUB_EVENT": ("EventNode", "EventNode"),
        "HAS_NARRATIVE": ("EventNode", "NarrativeNode"),
        "HAS_EVENT": ("Article", "EventNode"),
    }
    return endpoints.get(rel_type, ("Entity", "Entity"))


# Fallback schema for LadybugDB versions where SHOW_COLUMNS_BY_TABLE is unavailable
# (kept in sync with src/core/db/ladybug_schema.py)
_FALLBACK_NODE_COLUMNS: dict[str, list[str]] = {
    "Entity": [
        "id",
        "canonical_name",
        "type",
        "aliases",
        "description",
        "tier",
        "created_at",
        "updated_at",
    ],
    "Article": ["id", "pg_id"],
    "Community": [
        "id",
        "title",
        "summary",
        "level",
        "parent_id",
        "children_ids",
        "entity_count",
        "article_count",
        "rank",
        "period",
        "modularity",
        "created_at",
        "updated_at",
    ],
    "CommunityReport": [
        "id",
        "community_id",
        "title",
        "summary",
        "full_content",
        "key_entities",
        "key_relationships",
        "rank",
        "stale",
        "full_content_embedding",
        "created_at",
        "updated_at",
    ],
    "EventNode": [
        "id",
        "content",
        "attributes",
        "event_type",
        "name",
        "description",
        "event_time",
        "created_at",
        "embedding",
    ],
    "NarrativeNode": [
        "id",
        "source_bias",
        "frame",
        "tone",
        "emphasis",
        "created_at",
        "updated_at",
    ],
    "SchemaNode": [
        "id",
        "event_type",
        "pattern",
        "confidence",
        "created_at",
        "updated_at",
    ],
    "_CommunityMetadata": [
        "id",
        "last_full_rebuild_at",
        "last_incremental_update_at",
        "pending_entity_count",
        "entity_count",
        "modularity",
    ],
}

_FALLBACK_REL_PROPS: dict[str, list[str]] = {
    "MENTIONS": ["role"],
    "FOLLOWED_BY": ["time_gap_hours"],
    "EVENT_FOLLOWED_BY": ["time_gap_hours"],
    "CAUSES": ["confidence"],
    "ENABLES": ["strength"],
    "PREVENTS": [],
    "RELATED_TO": [
        "edge_type",
        "properties",
        "weight",
        "created_at",
        "updated_at",
    ],
    "HAS_ENTITY": [],
    "REPORTS_ON": [],
    "HAS_PARTICIPANT": ["role", "created_at"],
    "HAS_SUB_EVENT": ["created_at"],
    "HAS_NARRATIVE": ["created_at"],
    "HAS_EVENT": [],
}


def _ladybug_create_nodes(
    ladybug_conn,
    label: str,
    cols: list[str],
    nodes: list[dict],
) -> None:
    """Batch CREATE nodes in LadybugDB.

    Cypher's inline map literal ``{col: $col, ...}`` only accepts a
    single property in real_ladybug's parser — multi-property maps
    trigger "expected rule oC_SingleQuery" errors. We therefore CREATE
    with just the ``id`` PK, then SET every other column via
    ``SET n.`col` = $col``. Backticks protect against Cypher reserved
    words (e.g., ``type``).

    Vector columns (FLOAT[N], DOUBLE[], STRING[]) are skipped during
    CREATE+SET because the real_ladybug binder infers ANY type for
    Python lists, raising "Trying to a create a vector with ANY type".
    They are backfilled via a separate ``CREATE NODE`` Cypher list
    literal immediately after the node is created.
    """
    if "id" not in cols:
        raise RuntimeError(f"Cannot create {label} nodes: 'id' column required for CREATE")

    # Detect vector columns from the first node's value types
    vector_cols: set[str] = set()
    for node in nodes:
        for c in cols:
            v = node.get(c)
            if isinstance(v, list):
                vector_cols.add(c)
        if vector_cols:
            break

    # LadybugDB's binder has a bug: when a string parameter value looks
    # like a vector literal (e.g., '[]', '[1,2,3]' at certain positions),
    # it misinfers the type as a vector and raises
    # "Trying to a create a vector with ANY type". The workaround is to
    # inline string values as Cypher string literals (safely escaped)
    # so the binder infers STRING from the literal. Non-string scalars
    # (int/float/bool) are safe to pass as parameters.
    # Ref: scripts/data_io.py::_ladybug_create_nodes
    scalar_cols = [c for c in cols if c not in vector_cols]

    for props in nodes:
        # Build CREATE map literal. String values are inlined as escaped
        # Cypher string literals; other scalars use $param.
        non_none_cols = [c for c in scalar_cols if props.get(c) is not None]
        map_parts: list[str] = []
        param_dict: dict[str, Any] = {}
        for c in non_none_cols:
            v = props.get(c)
            if isinstance(v, str):
                # Inline as escaped Cypher string literal to avoid the
                # Kùzu binder bug on vector-looking strings like '[]'.
                escaped = v.replace("\\", "\\\\").replace("'", "\\'")
                map_parts.append(f"`{c}`: '{escaped}'")
            elif isinstance(v, bool):
                # bool before int because bool is a subclass of int
                map_parts.append(f"`{c}`: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                map_parts.append(f"`{c}`: ${c}")
                param_dict[c] = v
            else:
                # Fallback: parameterize (may fail for edge cases)
                map_parts.append(f"`{c}`: ${c}")
                param_dict[c] = v
        map_pairs = ", ".join(map_parts)
        cypher = f"CREATE (n:`{label}` {{{map_pairs}}})"
        try:
            ladybug_conn.execute(cypher, param_dict)  # nosemgrep: sqlalchemy-execute-raw-query
        except Exception as exc:
            raise RuntimeError(f"Failed to create node {label} with {param_dict}: {exc}") from exc

    # Backfill vector columns using a Cypher list literal. The literal
    # is rendered with Python repr (e.g., [0.1,0.2,...]) which LadybugDB's
    # binder accepts as a typed list when the node table schema declares
    # the column type explicitly.
    #
    # Performance: batch SET via CASE WHEN to avoid N+1 executes.
    # Each execute has network round-trip + parse + execute overhead; with
    # N=1000 nodes × M=1 vector column, the original N+1 loop ran ~1000
    # executes (5-20s). Batching at 50 nodes per Cypher reduces to ~20
    # executes (~95% reduction). id and literal are generated locally
    # from LadybugDB schema metadata — no injection surface, consistent
    # with the existing f-string Cypher pattern in this module.
    if not vector_cols:
        return

    _VECTOR_BACKFILL_BATCH = 50

    for vec_col in vector_cols:
        # Collect (id, literal) pairs for this vector column
        updates: list[tuple[Any, str]] = []
        for props in nodes:
            vec_val = props.get(vec_col)
            if not isinstance(vec_val, list) or not vec_val:
                continue
            # Render list literal: floats use repr to preserve precision
            if all(isinstance(x, (int, float)) for x in vec_val):
                literal = "[" + ",".join(repr(float(x)) for x in vec_val) + "]"
            else:
                # String list — quote each element
                literal = (
                    "["
                    + ",".join(f"'{str(x).replace(chr(39), chr(92) + chr(39))}'" for x in vec_val)
                    + "]"
                )
            node_id = props.get("id")
            if node_id is None:
                continue
            updates.append((node_id, literal))

        if not updates:
            continue

        # Batch SET: one Cypher per batch of _VECTOR_BACKFILL_BATCH nodes.
        # CASE n.id WHEN <id1> THEN <literal1> WHEN <id2> THEN <literal2> ... END
        for batch_start in range(0, len(updates), _VECTOR_BACKFILL_BATCH):
            batch = updates[batch_start : batch_start + _VECTOR_BACKFILL_BATCH]
            # Quote string ids; numeric ids stay bare. ids come from our
            # own LadybugDB schema metadata (no user input).
            case_clauses = " ".join(
                (
                    f"WHEN {u[0]!r} THEN {u[1]}"
                    if isinstance(u[0], str)
                    else f"WHEN {u[0]} THEN {u[1]}"
                )
                for u in batch
            )
            ids_list = [u[0] for u in batch]
            # Build IN clause: IN ['id1', 'id2', ...] or IN [1, 2, ...]
            ids_literal = (
                "[" + ", ".join(repr(i) if isinstance(i, str) else str(i) for i in ids_list) + "]"
            )
            batch_cypher = (
                f"MATCH (n:`{label}`) WHERE n.id IN {ids_literal} "
                f"SET n.`{vec_col}` = CASE n.id {case_clauses} END"
            )
            try:
                ladybug_conn.execute(batch_cypher)
            except Exception as exc:
                # Batch failure: fall back to per-node SET for this batch
                # so a single malformed vector doesn't abort the whole batch.
                for node_id, literal in batch:
                    update_cypher = f"MATCH (n:`{label}` {{id: $id}}) SET n.`{vec_col}` = {literal}"
                    try:
                        ladybug_conn.execute(  # nosemgrep: sqlalchemy-execute-raw-query
                            update_cypher, {"id": node_id}
                        )
                    except Exception as inner_exc:
                        # Vector backfill failure is non-fatal: log and continue
                        print(
                            f"WARN: Failed to backfill vector {label}.{vec_col} "
                            f"for id={node_id}: {inner_exc}"
                        )


def _ladybug_create_rels(
    ladybug_conn,
    rel_type: str,
    from_label: str,
    to_label: str,
    rel_props: list[str],
    rels: list[dict],
) -> None:
    """Batch CREATE relationships in LadybugDB.

    Property names are backtick-quoted because some may collide with
    Cypher reserved words.
    """
    # Build per-rel Cypher: properties in CREATE map literal.
    # Same Kùzu binder bug workaround as _ladybug_create_nodes:
    # string values are inlined as escaped Cypher string literals.
    for rel in rels:
        # Collect non-None prop values with timestamp conversion
        non_none_props: list[tuple[str, Any]] = []
        for p in rel_props:
            v = rel.get(p)
            if p.endswith("_at") or p.endswith("_time"):
                v = _to_epoch_seconds(v)
            if v is not None:
                non_none_props.append((p, v))

        map_parts: list[str] = []
        param_dict: dict[str, Any] = {"_from_id": rel["_from_id"], "_to_id": rel["_to_id"]}
        for p, v in non_none_props:
            if isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace("'", "\\'")
                map_parts.append(f"`{p}`: '{escaped}'")
            elif isinstance(v, bool):
                map_parts.append(f"`{p}`: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                map_parts.append(f"`{p}`: ${p}")
                param_dict[p] = v
            else:
                map_parts.append(f"`{p}`: ${p}")
                param_dict[p] = v

        map_literal = f" {{{', '.join(map_parts)}}}" if map_parts else ""

        cypher = (
            f"MATCH (a:`{from_label}` {{id: $_from_id}}), "
            f"(b:`{to_label}` {{id: $_to_id}}) "
            f"CREATE (a)-[r:`{rel_type}`{map_literal}]->(b)"
        )
        try:
            ladybug_conn.execute(cypher, param_dict)  # nosemgrep: sqlalchemy-execute-raw-query
        except Exception as exc:
            raise RuntimeError(f"Failed to create rel {rel_type} with {param_dict}: {exc}") from exc


# ── Cross-DB consistency verification (merged from verify_db_consistency.py) ──

# Columns whose names end with these suffixes are excluded from content hash
# because timestamps legitimately drift between primary and fallback DBs
# (PG→DuckDB migration rewrites NOW() defaults; Neo4j→LadybugDB converts
# datetime to INT64 epoch seconds). Excluding them yields a stable hash that
# reflects business data parity rather than migration-induced timestamp drift.
HASH_EXCLUDE_SUFFIXES = ("_at", "_time")

TABLE_SAMPLE_SIZE = 10
NODE_SAMPLE_SIZE = 5

# Tables where the business PK is not the column named "id".
# source_authorities.host is the natural key (one row per crawled host).
NON_ID_PK_TABLES: dict[str, str] = {
    "source_authorities": "host",
}


@dataclass
class CheckResult:
    """Result of a single consistency check (one table / label / rel-type)."""

    category: str  # "pg_duckdb" | "neo4j_ladybug"
    check_type: str  # "table" | "node_label" | "rel_type"
    name: str
    source_count: int = 0
    target_count: int = 0
    match: bool = False
    hash_source: str | None = None
    hash_target: str | None = None
    sample_match: bool | None = None
    error: str | None = None

    def is_pass(self) -> bool:
        """True iff this check passed (no error, count match, hash match, sample match).

        sample_match is None (N/A — e.g., empty table or rel-type sample skip)
        is treated as pass: we cannot evidence a mismatch when sampling is N/A.
        Only sample_match is False (sample drawn and diverged) counts as failure.
        """
        if self.error is not None:
            return False
        if not self.match:
            return False
        return self.sample_match is not False


@dataclass
class Report:
    """Full consistency report across both DB pairs."""

    pg_duckdb: list[CheckResult] = field(default_factory=list)
    neo4j_ladybug: list[CheckResult] = field(default_factory=list)

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            "pg_duckdb": _tally(self.pg_duckdb),
            "neo4j_ladybug": _tally(self.neo4j_ladybug),
        }

    def details(self) -> list[dict[str, Any]]:
        return [asdict(r) for r in (*self.pg_duckdb, *self.neo4j_ladybug)]

    def inconsistencies(self) -> list[dict[str, Any]]:
        return [asdict(r) for r in (*self.pg_duckdb, *self.neo4j_ladybug) if not r.is_pass()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": self.summary(),
            "details": self.details(),
            "inconsistencies": self.inconsistencies(),
        }


def _tally(results: list[CheckResult]) -> dict[str, int]:
    passed = sum(1 for r in results if r.is_pass())
    return {"pass": passed, "fail": len(results) - passed}


class _VerifyPgClient:
    """Async PostgreSQL client via SQLAlchemy async engine.

    Uses REPEATABLE READ isolation so all reads across the 27 tables see a
    single consistent snapshot (mirrors export_postgres_to_duckdb).
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._engine: Any = None

    async def connect(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        self._engine = create_async_engine(
            self.dsn, pool_pre_ping=True, isolation_level="REPEATABLE READ"
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def get_columns(self, table: str) -> list[str]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :t AND table_schema = 'public' "
                    "ORDER BY ordinal_position"
                ),
                {"t": table},
            )
            return [r[0] for r in result.fetchall()]

    async def count_rows(self, table: str) -> int:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            return int(result.scalar() or 0)

    async def compute_content_hash(self, table: str, columns: list[str], pk_col: str) -> str:
        """Compute a deterministic content hash for table rows.

        Per-row hash: MD5(concat_ws(chr(31), col1::text, col2::text, ...))
            chr(31) = ASCII Unit Separator — chosen because it never appears
            in well-formed text data, so it cannot collide with column values.
        Aggregate: string_agg(per_row_hash, '' ORDER BY pk) — fixed-length
            32-char MD5 strings need no separator.
        Outer: COALESCE(..., '') so empty tables hash to "" on both sides.

        Timestamp columns (*_at, *_time) are excluded because they drift
        between primary and fallback DBs (see HASH_EXCLUDE_SUFFIXES).
        """
        from sqlalchemy import text

        hash_cols = [c for c in columns if not c.endswith(HASH_EXCLUDE_SUFFIXES)]
        if not hash_cols:
            return ""
        col_expr = ", ".join(f'CAST("{c}" AS TEXT)' for c in hash_cols)
        row_hash = f"MD5(concat_ws(chr(31), {col_expr}))"
        sql = (
            f"SELECT COALESCE(string_agg({row_hash}, '' ORDER BY \"{pk_col}\"), '') "
            f'FROM "{table}"'
        )
        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql))
            return str(result.scalar() or "")

    async def sample_pks(self, table: str, pk_col: str, n: int = TABLE_SAMPLE_SIZE) -> list[Any]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(f'SELECT "{pk_col}" FROM "{table}" ORDER BY random() LIMIT {n}')
            )
            return [r[0] for r in result.fetchall()]

    async def fetch_rows_by_pks(
        self, table: str, columns: list[str], pk_col: str, pks: list[Any]
    ) -> dict[Any, tuple]:
        if not pks:
            return {}
        col_str = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f":p{i}" for i in range(len(pks)))
        params = {f"p{i}": v for i, v in enumerate(pks)}
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(f'SELECT {col_str} FROM "{table}" WHERE "{pk_col}" IN ({placeholders})'),
                params,
            )
            rows = result.fetchall()
        return {row[0]: tuple(row) for row in rows}


class _VerifyDuckDbClient:
    """Sync DuckDB client wrapped for async use via asyncio.to_thread.

    DuckDB's Python driver is synchronous; we wrap every call with
    asyncio.to_thread to avoid blocking the event loop. read_only=True
    prevents accidental writes during verification.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Any = None

    async def connect(self) -> None:
        import duckdb

        self._conn = await asyncio.to_thread(duckdb.connect, self.db_path, read_only=True)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def get_columns(self, table: str) -> list[str]:
        def _work() -> list[str]:
            rows = self._conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [table],
            ).fetchall()
            return [r[0] for r in rows]

        return await asyncio.to_thread(_work)

    async def count_rows(self, table: str) -> int:
        def _work() -> int:
            row = self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        return await asyncio.to_thread(_work)

    async def compute_content_hash(self, table: str, columns: list[str], pk_col: str) -> str:
        hash_cols = [c for c in columns if not c.endswith(HASH_EXCLUDE_SUFFIXES)]
        if not hash_cols:
            return ""
        col_expr = ", ".join(f'CAST("{c}" AS TEXT)' for c in hash_cols)
        row_hash = f"MD5(concat_ws(chr(31), {col_expr}))"
        sql = (
            f"SELECT COALESCE(string_agg({row_hash}, '' ORDER BY \"{pk_col}\"), '') "
            f'FROM "{table}"'
        )

        def _work() -> str:
            row = self._conn.execute(sql).fetchone()
            return str(row[0]) if row and row[0] is not None else ""

        return await asyncio.to_thread(_work)

    async def fetch_rows_by_pks(
        self, table: str, columns: list[str], pk_col: str, pks: list[Any]
    ) -> dict[Any, tuple]:
        if not pks:
            return {}
        col_str = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(["?"] * len(pks))

        def _work() -> dict[Any, tuple]:
            rows = self._conn.execute(
                f'SELECT {col_str} FROM "{table}" WHERE "{pk_col}" IN ({placeholders})',
                list(pks),
            ).fetchall()
            return {row[0]: tuple(row) for row in rows}

        return await asyncio.to_thread(_work)


class _VerifyNeo4jClient:
    """Sync Neo4j client wrapped for async use via asyncio.to_thread."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self._driver: Any = None

    async def connect(self) -> None:
        from neo4j import GraphDatabase

        self._driver = await asyncio.to_thread(
            GraphDatabase.driver, self.uri, auth=(self.user, self.password)
        )

    async def close(self) -> None:
        if self._driver is not None:
            await asyncio.to_thread(self._driver.close)
            self._driver = None

    async def count_nodes(self, label: str) -> int:
        def _work() -> int:
            with self._driver.session() as session:
                result = session.run(f"MATCH (n:`{label}`) RETURN count(n) AS cnt").single()
                return int(result["cnt"]) if result else 0

        return await asyncio.to_thread(_work)

    async def count_rels(self, rel_type: str) -> int:
        def _work() -> int:
            with self._driver.session() as session:
                result = session.run(
                    f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
                ).single()
                return int(result["cnt"]) if result else 0

        return await asyncio.to_thread(_work)

    async def sample_node_ids(self, label: str, n: int = NODE_SAMPLE_SIZE) -> list[str]:
        def _work() -> list[str]:
            with self._driver.session() as session:
                result = session.run(
                    f"MATCH (n:`{label}`) "
                    f"RETURN coalesce(n.id, n.pg_id, n.entity_id, n.community_id) AS id "
                    f"LIMIT {n}"
                )
                return [str(r["id"]) for r in result if r["id"] is not None]

        return await asyncio.to_thread(_work)

    async def fetch_node_props_by_ids(
        self, label: str, ids: list[str], props: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not ids or not props:
            return {}

        def _prop_expr(p: str) -> str:
            if p == "id":
                return "coalesce(n.id, n.pg_id, n.entity_id, n.community_id) AS id"
            return f"n.{p} AS {p}"

        prop_str = ", ".join(_prop_expr(p) for p in props)

        def _work() -> dict[str, dict[str, Any]]:
            with self._driver.session() as session:
                result = session.run(
                    f"MATCH (n:`{label}`) "
                    f"WHERE coalesce(n.id, n.pg_id, n.entity_id, n.community_id) IN $ids "
                    f"RETURN coalesce(n.id, n.pg_id, n.entity_id, n.community_id) AS _id, "
                    f"{prop_str}",
                    ids=list(ids),
                )
                out: dict[str, dict[str, Any]] = {}
                for record in result:
                    out[str(record["_id"])] = {
                        p: _verify_normalize_neo4j_value(record[p]) for p in props
                    }
                return out

        return await asyncio.to_thread(_work)


def _verify_normalize_neo4j_value(v: Any) -> Any:
    """Normalize a Neo4j value for cross-DB comparison.

    Neo4j returns its own datetime types; LadybugDB stores INT64 epoch seconds.
    Convert to a common Python representation before equality comparison.
    """
    if v is None:
        return None
    if hasattr(v, "to_native"):  # neo4j.time.DateTime → datetime
        v = v.to_native()
    if isinstance(v, datetime):
        return int(v.timestamp())
    return v


class _VerifyLadybugClient:
    """Sync LadybugDB client wrapped for async use via asyncio.to_thread."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: Any = None
        self._conn: Any = None

    async def connect(self) -> None:
        import real_ladybug as ladybug

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await asyncio.to_thread(ladybug.Database, self.db_path)
        self._conn = await asyncio.to_thread(ladybug.Connection, self._db)

    async def close(self) -> None:
        # real_ladybug doesn't require explicit close; release references.
        self._conn = None
        self._db = None

    async def count_nodes(self, label: str) -> int:
        def _work() -> int:
            result = self._conn.execute(f"MATCH (n:`{label}`) RETURN count(n) AS cnt")
            if result.has_next():
                return int(result.get_next()[0])
            return 0

        return await asyncio.to_thread(_work)

    async def count_rels(self, rel_type: str) -> int:
        def _work() -> int:
            result = self._conn.execute(f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt")
            if result.has_next():
                return int(result.get_next()[0])
            return 0

        return await asyncio.to_thread(_work)

    def node_columns(self, label: str) -> list[str]:
        """Return LadybugDB columns for a node label (sync; called from thread)."""
        return _get_ladybug_node_columns(self._conn, label)

    async def sample_node_ids(self, label: str, n: int = NODE_SAMPLE_SIZE) -> list[str]:
        def _work() -> list[str]:
            result = self._conn.execute(f"MATCH (n:`{label}`) RETURN n.id AS id LIMIT {n}")
            ids: list[str] = []
            while result.has_next():
                row = result.get_next()
                if row[0] is not None:
                    ids.append(str(row[0]))
            return ids

        return await asyncio.to_thread(_work)

    async def fetch_node_props_by_ids(
        self, label: str, ids: list[str], props: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not ids or not props:
            return {}
        prop_str = ", ".join(f"n.`{p}` AS {p}" for p in props)
        ids_literal = "[" + ", ".join(f"'{i}'" for i in ids) + "]"

        def _work() -> dict[str, dict[str, Any]]:
            result = self._conn.execute(
                f"MATCH (n:`{label}`) WHERE n.id IN {ids_literal} RETURN n.id AS _id, {prop_str}"
            )
            out: dict[str, dict[str, Any]] = {}
            while result.has_next():
                row = result.get_next()
                row_id = str(row[0])
                props_dict = {
                    p: _verify_normalize_ladybug_value(row[i + 1]) for i, p in enumerate(props)
                }
                out[row_id] = props_dict
            return out

        return await asyncio.to_thread(_work)


def _verify_normalize_ladybug_value(v: Any) -> Any:
    """Normalize a LadybugDB value for cross-DB comparison."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return int(v.timestamp())
    return v


def _verify_pk_col_for(table: str, columns: list[str]) -> str:
    """Return the primary key column name for a table.

    Most tables use `id` as PK. source_authorities uses `host`. Falls back to
    first column if neither `id` nor a known override is present.
    """
    if "id" in columns:
        return "id"
    if table in NON_ID_PK_TABLES:
        return NON_ID_PK_TABLES[table]
    return columns[0]


def _verify_normalize_value(v: Any) -> Any:
    """Normalize a single cell value for cross-DB comparison.

    Handles known type divergences between PG/DuckDB drivers and
    Neo4j/LadybugDB drivers (datetime→epoch, bytes→hex, numpy scalars,
    JSON str-vs-dict, pgvector float rounding, dict key sorting).
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return int(v.timestamp())
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if hasattr(v, "tolist") and not isinstance(v, (list, tuple, str, bytes)):
        try:
            return _verify_normalize_value(v.tolist())
        except Exception:
            pass
    if hasattr(v, "item") and not isinstance(v, (list, tuple, str, bytes)):
        try:
            return v.item()
        except Exception:
            return v
    if isinstance(v, str):
        stripped = v.strip()
        if stripped and stripped[0] in "{[":
            try:
                return _verify_normalize_value(json.loads(stripped))
            except (json.JSONDecodeError, ValueError):
                pass
        return v
    if isinstance(v, (list, tuple)):
        normalized = [_verify_normalize_value(x) for x in v]
        if normalized and all(isinstance(x, float) for x in normalized):
            return [round(x, 6) for x in normalized]
        return normalized
    if isinstance(v, dict):
        return {k: _verify_normalize_value(val) for k, val in sorted(v.items())}
    return v


def _verify_values_equal(a: Any, b: Any) -> bool:
    """Compare two normalized values with float tolerance for vectors."""
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b, strict=True):
            if isinstance(x, float) and isinstance(y, float):
                if not math.isclose(x, y, rel_tol=1e-5, abs_tol=2e-6):
                    return False
            elif x != y:
                return False
        return True
    return a == b


async def compare_pg_duckdb(pg: _VerifyPgClient, duck: _VerifyDuckDbClient) -> list[CheckResult]:
    """Compare all 27 tables between PostgreSQL and DuckDB.

    For each table: common columns → row count → content MD5 hash → 10-row
    sample field-by-field. Single-table errors are recorded but do not abort
    the loop (Rule 12).
    """
    results: list[CheckResult] = []
    for table in EXPECTED_TABLES:
        result = CheckResult(category="pg_duckdb", check_type="table", name=table)
        try:
            pg_cols = await pg.get_columns(table)
            duck_cols = await duck.get_columns(table)
            if not pg_cols:
                raise RuntimeError(f"table not in PG: {table}")
            if not duck_cols:
                raise RuntimeError(f"table not in DuckDB: {table}")
            common = [c for c in duck_cols if c in pg_cols]
            if not common:
                raise RuntimeError(f"no common columns for table {table}")

            pk = _verify_pk_col_for(table, common)

            pg_count = await pg.count_rows(table)
            duck_count = await duck.count_rows(table)
            result.source_count = pg_count
            result.target_count = duck_count
            result.match = pg_count == duck_count

            if pg_count > 0 and pg_count == duck_count:
                result.hash_source = await pg.compute_content_hash(table, common, pk)
                result.hash_target = await duck.compute_content_hash(table, common, pk)

            if pg_count > 0 and pg_count == duck_count:
                sample_pks = await pg.sample_pks(table, pk, TABLE_SAMPLE_SIZE)
                pg_rows = await pg.fetch_rows_by_pks(table, common, pk, sample_pks)
                duck_rows = await duck.fetch_rows_by_pks(table, common, pk, sample_pks)
                cmp_cols = [c for c in common if not c.endswith(HASH_EXCLUDE_SUFFIXES)]
                col_idx = {c: i for i, c in enumerate(common)}
                sample_match = True
                for pk_val, pg_row in pg_rows.items():
                    duck_row = duck_rows.get(pk_val)
                    if duck_row is None:
                        sample_match = False
                        break
                    for c in cmp_cols:
                        if not _verify_values_equal(
                            _verify_normalize_value(pg_row[col_idx[c]]),
                            _verify_normalize_value(duck_row[col_idx[c]]),
                        ):
                            sample_match = False
                            break
                    if not sample_match:
                        break
                result.sample_match = sample_match
                if not sample_match:
                    result.match = False
            else:
                result.sample_match = None
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.match = False
        results.append(result)
        _verify_print_table_result(result)
    return results


async def compare_neo4j_ladybug(
    neo: _VerifyNeo4jClient, lady: _VerifyLadybugClient
) -> list[CheckResult]:
    """Compare 8 node labels and 13 rel types between Neo4j and LadybugDB.

    Node labels: count + (if match & >0) 5-node property sample.
    Rel types: count only (per-rel property comparison unreliable due to
    LadybugDB FROM/TO label constraints differing from Neo4j's schemaless rels).
    """
    results: list[CheckResult] = []

    for label in EXPECTED_NODE_LABELS:
        result = CheckResult(category="neo4j_ladybug", check_type="node_label", name=label)
        try:
            neo_count = await neo.count_nodes(label)
            lady_count = await lady.count_nodes(label)
            result.source_count = neo_count
            result.target_count = lady_count
            result.match = neo_count == lady_count

            if neo_count > 0 and neo_count == lady_count:
                lady_cols = lady.node_columns(label)
                if not lady_cols:
                    result.sample_match = None
                else:
                    cmp_props = [p for p in lady_cols if not p.endswith(HASH_EXCLUDE_SUFFIXES)]
                    if not cmp_props:
                        result.sample_match = None
                    else:
                        sample_ids = await neo.sample_node_ids(label, NODE_SAMPLE_SIZE)
                        if sample_ids:
                            neo_props = await neo.fetch_node_props_by_ids(
                                label, sample_ids, cmp_props
                            )
                            lady_props = await lady.fetch_node_props_by_ids(
                                label, sample_ids, cmp_props
                            )
                            sample_match = True
                            for sid in sample_ids:
                                np = neo_props.get(sid, {})
                                lp = lady_props.get(sid, {})
                                for p in cmp_props:
                                    if not _verify_values_equal(
                                        _verify_normalize_value(np.get(p)),
                                        _verify_normalize_value(lp.get(p)),
                                    ):
                                        sample_match = False
                                        break
                                if not sample_match:
                                    break
                            result.sample_match = sample_match
                            if not sample_match:
                                result.match = False
                        else:
                            result.sample_match = None
            else:
                result.sample_match = None
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.match = False
        results.append(result)
        _verify_print_graph_result(result)

    for rel_type in EXPECTED_REL_TYPES:
        result = CheckResult(category="neo4j_ladybug", check_type="rel_type", name=rel_type)
        try:
            neo_count = await neo.count_rels(rel_type)
            lady_count = await lady.count_rels(rel_type)
            result.source_count = neo_count
            result.target_count = lady_count
            result.match = neo_count == lady_count
            result.sample_match = None
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.match = False
        results.append(result)
        _verify_print_graph_result(result)
    return results


def _verify_print_table_result(r: CheckResult) -> None:
    if r.error is not None:
        status = "ERROR"
    elif r.is_pass():
        status = "PASS"
    else:
        status = "FAIL"
    count_str = f"PG={r.source_count} DuckDB={r.target_count}"
    hash_str = ""
    if r.hash_source is not None and r.hash_target is not None:
        match_str = "match" if r.hash_source == r.hash_target else "DIFF"
        hash_str = f" hash={match_str}"
    sample_str = ""
    if r.sample_match is not None:
        sample_str = f" sample={'OK' if r.sample_match else 'DIFF'}"
    err_str = f" err={r.error}" if r.error else ""
    print(f"  [{status:>5}] {r.name:<32s} {count_str}{hash_str}{sample_str}{err_str}")


def _verify_print_graph_result(r: CheckResult) -> None:
    if r.error is not None:
        status = "ERROR"
    elif r.is_pass():
        status = "PASS"
    else:
        status = "FAIL"
    count_str = f"Neo4j={r.source_count} LadybugDB={r.target_count}"
    sample_str = ""
    if r.sample_match is not None:
        sample_str = f" sample={'OK' if r.sample_match else 'DIFF'}"
    err_str = f" err={r.error}" if r.error else ""
    print(f"  [{status:>5}] {r.check_type:<10s} {r.name:<24s} {count_str}{sample_str}{err_str}")


async def _verify_consistency(args: argparse.Namespace) -> int:
    """Verify data consistency across PG↔DuckDB and Neo4j↔LadybugDB.

    Formerly the standalone verify_db_consistency.py. Writes a JSON report to
    --output (default temp/consistency_report.json). Exit: 0 all pass / 1
    inconsistency / 2 usage error.
    """
    report = Report()
    mode = args.mode

    # ── PG ↔ DuckDB ────────────────────────────────────────────────────
    if mode in ("all", "pg-duckdb"):
        print("\n=== Comparing PostgreSQL ↔ DuckDB ===")
        if not args.pg_dsn:
            print(
                "[ERROR] --pg-dsn (or $WEAVER_POSTGRES__DSN) required for pg-duckdb mode",
                file=sys.stderr,
            )
            if mode == "pg-duckdb":
                return 2
        elif not Path(args.duckdb_path).exists():
            print(f"[ERROR] DuckDB file not found: {args.duckdb_path}", file=sys.stderr)
            if mode == "pg-duckdb":
                return 2
        else:
            pg = _VerifyPgClient(args.pg_dsn)
            duck = _VerifyDuckDbClient(args.duckdb_path)
            try:
                await pg.connect()
                await duck.connect()
                dsn_display = args.pg_dsn.split("@")[-1]
                print(f"Connected: PG ({dsn_display}) ↔ DuckDB ({args.duckdb_path})")
                print(f"Comparing {len(EXPECTED_TABLES)} tables...")
                report.pg_duckdb = await compare_pg_duckdb(pg, duck)
            finally:
                await pg.close()
                await duck.close()

    # ── Neo4j ↔ LadybugDB ──────────────────────────────────────────────
    if mode in ("all", "neo4j-ladybug"):
        print("\n=== Comparing Neo4j ↔ LadybugDB ===")
        if not args.neo4j_password:
            print(
                "[ERROR] --neo4j-password (or $WEAVER_NEO4J__PASSWORD) "
                "required for neo4j-ladybug mode",
                file=sys.stderr,
            )
            if mode == "neo4j-ladybug":
                return 2
        elif not Path(args.ladybug_path).exists():
            print(f"[ERROR] LadybugDB file not found: {args.ladybug_path}", file=sys.stderr)
            if mode == "neo4j-ladybug":
                return 2
        else:
            neo = _VerifyNeo4jClient(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
            lady = _VerifyLadybugClient(args.ladybug_path)
            try:
                await neo.connect()
                await lady.connect()
                print(f"Connected: Neo4j ({args.neo4j_uri}) ↔ LadybugDB ({args.ladybug_path})")
                print(
                    f"Comparing {len(EXPECTED_NODE_LABELS)} node labels "
                    f"and {len(EXPECTED_REL_TYPES)} rel types..."
                )
                report.neo4j_ladybug = await compare_neo4j_ladybug(neo, lady)
            finally:
                await neo.close()
                await lady.close()

    # ── Summary & report ───────────────────────────────────────────────
    summary = report.summary()
    print("\n=== Summary ===")
    print(
        f"  PG↔DuckDB:      pass={summary['pg_duckdb']['pass']:>3}  "
        f"fail={summary['pg_duckdb']['fail']:>3}"
    )
    print(
        f"  Neo4j↔Ladybug:  pass={summary['neo4j_ladybug']['pass']:>3}  "
        f"fail={summary['neo4j_ladybug']['fail']:>3}"
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str))
    print(f"\nReport saved to: {out_path}")

    total_fail = summary["pg_duckdb"]["fail"] + summary["neo4j_ladybug"]["fail"]
    return 0 if total_fail == 0 else 1


# ── CLI entry point ─────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data_io",
        description="Weaver data import/export tool (PG↔DuckDB, Neo4j→LadybugDB)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # import subcommand
    p_import = sub.add_parser("import", help="Import data into a primary database")
    p_import.add_argument("--from", dest="from_type", required=True, choices=["duckdb"])
    p_import.add_argument("--to", dest="to_type", required=True, choices=["postgres"])
    p_import.add_argument("--duckdb-path", required=True)
    p_import.add_argument("--pg-dsn", required=True)

    # export subcommand
    p_export = sub.add_parser("export", help="Export data from a primary database")
    p_export.add_argument(
        "--from",
        dest="from_type",
        required=True,
        choices=["postgres", "neo4j"],
    )
    p_export.add_argument("--to", dest="to_type", required=True, choices=["duckdb", "ladybug"])
    # PG source
    p_export.add_argument("--pg-dsn")
    # DuckDB target
    p_export.add_argument("--duckdb-path")
    # Neo4j source
    p_export.add_argument("--neo4j-uri")
    p_export.add_argument("--neo4j-user", default="neo4j")
    p_export.add_argument("--neo4j-password")
    # Ladybug target
    p_export.add_argument("--ladybug-path")

    # verify subcommand
    p_verify = sub.add_parser(
        "verify",
        help="Verify data consistency across PG↔DuckDB and Neo4j↔LadybugDB",
    )
    p_verify.add_argument(
        "--mode",
        choices=["all", "pg-duckdb", "neo4j-ladybug"],
        default="all",
        help="Comparison mode (default: all)",
    )
    p_verify.add_argument(
        "--pg-dsn",
        default=os.environ.get("WEAVER_POSTGRES__DSN"),
        help="PostgreSQL DSN (default: $WEAVER_POSTGRES__DSN)",
    )
    p_verify.add_argument("--duckdb-path", default="data/weaver.duckdb", help="DuckDB file path")
    p_verify.add_argument(
        "--neo4j-uri",
        default=os.environ.get("WEAVER_NEO4J__URI", "bolt://localhost:7687"),
        help="Neo4j URI (default: bolt://localhost:7687)",
    )
    p_verify.add_argument(
        "--neo4j-user",
        default=os.environ.get("WEAVER_NEO4J__USER", "neo4j"),
        help="Neo4j username (default: neo4j)",
    )
    p_verify.add_argument(
        "--neo4j-password",
        default=os.environ.get("WEAVER_NEO4J__PASSWORD"),
        help="Neo4j password (default: $WEAVER_NEO4J__PASSWORD)",
    )
    p_verify.add_argument("--ladybug-path", default="data/weaver.lbug", help="LadybugDB file path")
    p_verify.add_argument(
        "--output",
        default="temp/consistency_report.json",
        help="Report output path (default: temp/consistency_report.json)",
    )

    return parser


async def _async_main(args: argparse.Namespace) -> int:
    if args.command == "import":
        if args.from_type == "duckdb" and args.to_type == "postgres":
            await import_duckdb_to_postgres(
                duckdb_path=args.duckdb_path,
                pg_dsn=args.pg_dsn,
            )
            print(f"[OK] DuckDB → PostgreSQL import completed: {args.duckdb_path} → {args.pg_dsn}")
            return 0
    elif args.command == "export":
        if args.from_type == "postgres" and args.to_type == "duckdb":
            if not args.pg_dsn or not args.duckdb_path:
                print("[ERROR] --pg-dsn and --duckdb-path are required", file=sys.stderr)
                return 2
            await export_postgres_to_duckdb(
                pg_dsn=args.pg_dsn,
                duckdb_path=args.duckdb_path,
            )
            print(f"[OK] PostgreSQL → DuckDB export completed: {args.pg_dsn} → {args.duckdb_path}")
            return 0
        if args.from_type == "neo4j" and args.to_type == "ladybug":
            if not all([args.neo4j_uri, args.neo4j_password, args.ladybug_path]):
                print(
                    "[ERROR] --neo4j-uri, --neo4j-password, --ladybug-path are required",
                    file=sys.stderr,
                )
                return 2
            await export_neo4j_to_ladybug(
                neo4j_uri=args.neo4j_uri,
                neo4j_user=args.neo4j_user,
                neo4j_password=args.neo4j_password,
                ladybug_path=args.ladybug_path,
            )
            print(
                f"[OK] Neo4j → LadybugDB export completed: {args.neo4j_uri} → {args.ladybug_path}"
            )
            return 0
    elif args.command == "verify":
        return await _verify_consistency(args)

    print(f"[ERROR] Unknown command combination: {args}", file=sys.stderr)
    return 2


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(_async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
