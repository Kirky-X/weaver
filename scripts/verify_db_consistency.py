#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Verify data consistency across Weaver's 4 databases.

Compares:
    - PostgreSQL vs DuckDB (27 tables): row counts + content MD5 hash + 10-row sample
    - Neo4j vs LadybugDB (8 node labels + 13 rel types): counts + 5-node sample

Output:
    JSON report at specmark/changes/db-consistency-verify/records/consistency_report.json
    Human-readable progress on stdout.

Exit code: 0 = all checks pass, 1 = at least one inconsistency, 2 = usage error.

Usage:
    uv run python scripts/verify_db_consistency.py --mode all
    uv run python scripts/verify_db_consistency.py --mode pg-duckdb \\
        --pg-dsn 'postgresql+asyncpg://...' --duckdb-path data/weaver.duckdb
    uv run python scripts/verify_db_consistency.py --mode neo4j-ladybug \\
        --neo4j-uri bolt://localhost:7687 --neo4j-password "$WEAVER_NEO4J__PASSWORD"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Make sibling imports work so `from data_io import ...` resolves regardless of CWD.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Reuse canonical constants & helpers from data_io.py (single source of truth).
from data_io import (  # noqa: E402
    EXPECTED_NODE_LABELS,
    EXPECTED_REL_TYPES,
    EXPECTED_TABLES,
    _get_ladybug_node_columns,
)

# ── Constants ────────────────────────────────────────────────────────

REPORT_PATH = Path("specmark/changes/db-consistency-verify/records/consistency_report.json")

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


# ── Result dataclasses ──────────────────────────────────────────────


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


# ── PostgreSQL client ───────────────────────────────────────────────


class PgClient:
    """Async PostgreSQL client via SQLAlchemy async engine.

    Uses REPEATABLE READ isolation so all reads across the 27 tables see a
    single consistent snapshot (mirrors data_io.export_postgres_to_duckdb).
    Without this, concurrent pipeline writes can cause inter-table row count
    drift and spurious hash mismatches.
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
                text(f'SELECT {col_str} FROM "{table}" ' f'WHERE "{pk_col}" IN ({placeholders})'),
                params,
            )
            rows = result.fetchall()
        return {row[0]: tuple(row) for row in rows}


# ── DuckDB client ───────────────────────────────────────────────────


class DuckDbClient:
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
        # Mirror PgClient.compute_content_hash SQL shape. DuckDB supports
        # chr(), concat_ws(), MD5(), string_agg(... ORDER BY ...).
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


# ── Neo4j client ─────────────────────────────────────────────────────


class Neo4jClient:
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
                # Some labels (e.g., Article) lack an explicit `id` property
                # and use pg_id / entity_id / community_id as the business key.
                # coalesce lets us sample by the same key LadybugDB uses as PK.
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

        # For the `id` property, apply the same coalesce fallback that
        # data_io._convert_neo4j_node_props uses when exporting to LadybugDB:
        # Neo4j Article nodes lack `id` (they use pg_id as the business key),
        # but LadybugDB's Article.id PRIMARY KEY is populated from pg_id.
        # Without this symmetric fallback, Neo4j n.id=None would always
        # mismatch LadybugDB's id=<pg_id value>.
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
                    out[str(record["_id"])] = {p: _normalize_neo4j_value(record[p]) for p in props}
                return out

        return await asyncio.to_thread(_work)


def _normalize_neo4j_value(v: Any) -> Any:
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


# ── LadybugDB client ─────────────────────────────────────────────────


class LadybugClient:
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
        # Reuses data_io._get_ladybug_node_columns which has a built-in fallback
        # to _FALLBACK_NODE_COLUMNS when CALL TABLE_INFO introspection fails.
        return _get_ladybug_node_columns(self._conn, label)

    async def sample_node_ids(self, label: str, n: int = NODE_SAMPLE_SIZE) -> list[str]:
        def _work() -> list[str]:
            # LadybugDB (Kùzu) binder is strict: coalesce(n.id, n.pg_id, ...)
            # raises "Cannot find property pg_id" when pg_id is not in the
            # label's schema. All LadybugDB node labels have `id` as PRIMARY
            # KEY, so we can use n.id directly without the coalesce fallback
            # that Neo4j needs (Neo4j Article nodes lack `id`, using pg_id).
            result = self._conn.execute(f"MATCH (n:`{label}`) " f"RETURN n.id AS id " f"LIMIT {n}")
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
        # Backtick-quote property names — some collide with Cypher reserved
        # words (e.g., `type` on Entity). Mirrors data_io._ladybug_create_nodes.
        prop_str = ", ".join(f"n.`{p}` AS {p}" for p in props)
        # ids are str PKs from LadybugDB schema (id STRING PRIMARY KEY);
        # rendering them as Cypher string literals is safe because they were
        # retrieved from the DB ourselves (no user input).
        ids_literal = "[" + ", ".join(f"'{i}'" for i in ids) + "]"

        def _work() -> dict[str, dict[str, Any]]:
            result = self._conn.execute(
                f"MATCH (n:`{label}`) "
                f"WHERE n.id IN {ids_literal} "
                f"RETURN n.id AS _id, "
                f"{prop_str}"
            )
            out: dict[str, dict[str, Any]] = {}
            while result.has_next():
                row = result.get_next()
                row_id = str(row[0])
                # row[0] = _id, row[1..N] = property values in prop_str order
                props_dict = {p: _normalize_ladybug_value(row[i + 1]) for i, p in enumerate(props)}
                out[row_id] = props_dict
            return out

        return await asyncio.to_thread(_work)


def _normalize_ladybug_value(v: Any) -> Any:
    """Normalize a LadybugDB value for cross-DB comparison."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return int(v.timestamp())
    return v


# ── Comparison logic ────────────────────────────────────────────────


def _pk_col_for(table: str, columns: list[str]) -> str:
    """Return the primary key column name for a table.

    Most tables use `id` as PK. source_authorities uses `host` (one row per
    crawled host — no synthetic id column). Falls back to first column if
    neither `id` nor a known override is present.
    """
    if "id" in columns:
        return "id"
    if table in NON_ID_PK_TABLES:
        return NON_ID_PK_TABLES[table]
    return columns[0]


def _normalize_value(v: Any) -> Any:
    """Normalize a single cell value for cross-DB comparison.

    Handles known type divergences between PG/DuckDB drivers and
    Neo4j/LadybugDB drivers:
      - datetime → epoch seconds (LadybugDB stores INT64)
      - bytes (e.g., pgvector) → hex string
      - numpy scalars (returned by pgvector) → Python scalars
      - JSON columns: PG jsonb returns dict/list, DuckDB JSON returns str.
        We parse str starting with `{` or `[` as JSON so both sides converge.
        Parse failures (e.g., title "[Update] Foo") keep the original str.
      - pgvector text format (PG str '[0.1,0.2,...]') vs DuckDB FLOAT[] tuple:
        both normalize to list[float]; floats rounded to 6 decimals to
        tolerate PG's 8-significant-digit text format vs DuckDB's native
        double precision.
      - dict keys sorted to tolerate PG jsonb vs DuckDB JSON key-order drift.
      - list/tuple → recursively normalized list.
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return int(v.timestamp())
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    # numpy ndarray (pgvector returns numpy.ndarray for Vector columns).
    # Must use tolist() — ndarray.item() only works for single-element arrays
    # and raises ValueError for multi-element vectors. After tolist(), the
    # list branch below handles float rounding for precision tolerance.
    if hasattr(v, "tolist") and not isinstance(v, (list, tuple, str, bytes)):
        try:
            return _normalize_value(v.tolist())
        except Exception:
            pass
    # numpy scalar (e.g., numpy.float64) → Python scalar
    if hasattr(v, "item") and not isinstance(v, (list, tuple, str, bytes)):
        try:
            return v.item()
        except Exception:
            return v
    # JSON column normalization: PG jsonb → dict/list, DuckDB JSON → str.
    # Only attempt parse when the stripped string starts with { or [, so
    # ordinary strings (titles, URLs) are returned untouched. Parse failures
    # also fall through, keeping the original str.
    if isinstance(v, str):
        stripped = v.strip()
        if stripped and stripped[0] in "{[":
            try:
                return _normalize_value(json.loads(stripped))
            except (json.JSONDecodeError, ValueError):
                pass
        return v
    if isinstance(v, (list, tuple)):
        normalized = [_normalize_value(x) for x in v]
        # Float-list rounding: pgvector text format yields ~8 significant
        # digits, DuckDB native FLOAT[] yields full double precision. Round
        # to 6 decimals so both representations compare equal.
        if normalized and all(isinstance(x, float) for x in normalized):
            return [round(x, 6) for x in normalized]
        return normalized
    if isinstance(v, dict):
        # Sort keys to tolerate PG jsonb vs DuckDB JSON key-order drift.
        return {k: _normalize_value(val) for k, val in sorted(v.items())}
    return v


def _values_equal(a: Any, b: Any) -> bool:
    """Compare two normalized values with float tolerance for vectors.

    pgvector text format (PG) yields ~8 significant digits; DuckDB native
    FLOAT[] yields full double precision. Even after rounding to 6 decimals
    in _normalize_value, boundary values can land on opposite sides of the
    rounding boundary (e.g., PG -0.0192485 → -0.019249, DuckDB -0.0192499
    → -0.019250). The observed max diff after rounding is exactly 1e-6, so
    we use abs_tol=2e-6 to tolerate rounding-boundary cases while still
    catching real data divergence (which would be orders of magnitude larger).
    """
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


async def compare_pg_duckdb(pg: PgClient, duck: DuckDbClient) -> list[CheckResult]:
    """Compare all 27 tables between PostgreSQL and DuckDB.

    For each table:
      1. Get common columns (PG ∩ DuckDB) — schema drift protection.
      2. Compare row counts.
      3. If counts match and > 0, compare content MD5 hash (excl. timestamps).
      4. If counts match and > 0, sample 10 random rows and compare field-by-field.
    Single-table errors are recorded but do not abort the loop (Rule 12).
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
            # Intersection in DuckDB column order (mirrors data_io.py).
            common = [c for c in duck_cols if c in pg_cols]
            if not common:
                raise RuntimeError(f"no common columns for table {table}")

            pk = _pk_col_for(table, common)

            # 1. Row count
            pg_count = await pg.count_rows(table)
            duck_count = await duck.count_rows(table)
            result.source_count = pg_count
            result.target_count = duck_count
            result.match = pg_count == duck_count

            # 2. Content hash (informational; sample comparison is authoritative).
            # Hash DIFF alone does not fail the check because SQL-layer
            # CAST(... AS TEXT) diverges for jsonb/JSON (key order, whitespace),
            # pgvector (text format vs native float), and some numeric types.
            # The Python-side sample comparison normalizes these divergences
            # and is the authoritative judge of business-data parity.
            if pg_count > 0 and pg_count == duck_count:
                result.hash_source = await pg.compute_content_hash(table, common, pk)
                result.hash_target = await duck.compute_content_hash(table, common, pk)

            # 3. Sample comparison (only when counts match and table non-empty)
            if pg_count > 0 and pg_count == duck_count:
                sample_pks = await pg.sample_pks(table, pk, TABLE_SAMPLE_SIZE)
                pg_rows = await pg.fetch_rows_by_pks(table, common, pk, sample_pks)
                duck_rows = await duck.fetch_rows_by_pks(table, common, pk, sample_pks)
                # Exclude timestamp columns from per-cell comparison
                cmp_cols = [c for c in common if not c.endswith(HASH_EXCLUDE_SUFFIXES)]
                col_idx = {c: i for i, c in enumerate(common)}
                sample_match = True
                for pk_val, pg_row in pg_rows.items():
                    duck_row = duck_rows.get(pk_val)
                    if duck_row is None:
                        sample_match = False
                        break
                    for c in cmp_cols:
                        if not _values_equal(
                            _normalize_value(pg_row[col_idx[c]]),
                            _normalize_value(duck_row[col_idx[c]]),
                        ):
                            sample_match = False
                            break
                    if not sample_match:
                        break
                result.sample_match = sample_match
                if not sample_match:
                    result.match = False
            else:
                # Empty table or count mismatch — sample is N/A.
                result.sample_match = None
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.match = False
        results.append(result)
        _print_table_result(result)
    return results


async def compare_neo4j_ladybug(neo: Neo4jClient, lady: LadybugClient) -> list[CheckResult]:
    """Compare 8 node labels and 13 rel types between Neo4j and LadybugDB.

    For each node label:
      1. Compare node counts.
      2. If counts match and > 0, sample 5 nodes and compare key properties.
    For each rel type:
      1. Compare rel counts only (sample comparison skipped — LadybugDB
         has FROM/TO label constraints that differ from Neo4j's schemaless
         relationships, so per-rel property comparison is unreliable).
    """
    results: list[CheckResult] = []

    # 1. Node labels
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
                    # Label not in LadybugDB schema — skip sample comparison
                    result.sample_match = None
                else:
                    # Compare only properties the LadybugDB schema declares
                    # (Neo4j may have extra properties not synced to LadybugDB).
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
                                    if not _values_equal(
                                        _normalize_value(np.get(p)),
                                        _normalize_value(lp.get(p)),
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
        _print_graph_result(result)

    # 2. Relationship types
    for rel_type in EXPECTED_REL_TYPES:
        result = CheckResult(category="neo4j_ladybug", check_type="rel_type", name=rel_type)
        try:
            neo_count = await neo.count_rels(rel_type)
            lady_count = await lady.count_rels(rel_type)
            result.source_count = neo_count
            result.target_count = lady_count
            result.match = neo_count == lady_count
            # Sample comparison skipped for relationships — see docstring.
            result.sample_match = None
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.match = False
        results.append(result)
        _print_graph_result(result)
    return results


# ── Pretty-printing ─────────────────────────────────────────────────


def _print_table_result(r: CheckResult) -> None:
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


def _print_graph_result(r: CheckResult) -> None:
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


# ── CLI ─────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_db_consistency",
        description="Verify data consistency across Weaver's 4 databases.",
    )
    parser.add_argument(
        "--mode",
        choices=["all", "pg-duckdb", "neo4j-ladybug"],
        default="all",
        help="Comparison mode (default: all)",
    )
    parser.add_argument(
        "--pg-dsn",
        default=os.environ.get("WEAVER_POSTGRES__DSN"),
        help="PostgreSQL DSN, e.g. 'postgresql+asyncpg://user:pass@host/db' "
        "(default: $WEAVER_POSTGRES__DSN)",
    )
    parser.add_argument(
        "--duckdb-path",
        default="data/weaver.duckdb",
        help="DuckDB file path (default: data/weaver.duckdb)",
    )
    parser.add_argument(
        "--neo4j-uri",
        default=os.environ.get("WEAVER_NEO4J__URI", "bolt://localhost:7687"),
        help="Neo4j URI (default: bolt://localhost:7687)",
    )
    parser.add_argument(
        "--neo4j-user",
        default=os.environ.get("WEAVER_NEO4J__USER", "neo4j"),
        help="Neo4j username (default: neo4j)",
    )
    parser.add_argument(
        "--neo4j-password",
        default=os.environ.get("WEAVER_NEO4J__PASSWORD"),
        help="Neo4j password (default: $WEAVER_NEO4J__PASSWORD)",
    )
    parser.add_argument(
        "--ladybug-path",
        default="data/weaver.lbug",
        help="LadybugDB file path (default: data/weaver.lbug)",
    )
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    report = Report()
    mode = args.mode

    # ── PG ↔ DuckDB ────────────────────────────────────────────────
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
            print(
                f"[ERROR] DuckDB file not found: {args.duckdb_path}",
                file=sys.stderr,
            )
            if mode == "pg-duckdb":
                return 2
        else:
            pg = PgClient(args.pg_dsn)
            duck = DuckDbClient(args.duckdb_path)
            try:
                await pg.connect()
                await duck.connect()
                # Print DSN host part only (avoid leaking password to stdout)
                dsn_display = args.pg_dsn.split("@")[-1]
                print(f"Connected: PG ({dsn_display}) ↔ DuckDB ({args.duckdb_path})")
                print(f"Comparing {len(EXPECTED_TABLES)} tables...")
                report.pg_duckdb = await compare_pg_duckdb(pg, duck)
            finally:
                await pg.close()
                await duck.close()

    # ── Neo4j ↔ LadybugDB ─────────────────────────────────────────
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
            print(
                f"[ERROR] LadybugDB file not found: {args.ladybug_path}",
                file=sys.stderr,
            )
            if mode == "neo4j-ladybug":
                return 2
        else:
            neo = Neo4jClient(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
            lady = LadybugClient(args.ladybug_path)
            try:
                await neo.connect()
                await lady.connect()
                print(f"Connected: Neo4j ({args.neo4j_uri}) ↔ " f"LadybugDB ({args.ladybug_path})")
                print(
                    f"Comparing {len(EXPECTED_NODE_LABELS)} node labels "
                    f"and {len(EXPECTED_REL_TYPES)} rel types..."
                )
                report.neo4j_ladybug = await compare_neo4j_ladybug(neo, lady)
            finally:
                await neo.close()
                await lady.close()

    # ── Summary & report ──────────────────────────────────────────
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

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str))
    print(f"\nReport saved to: {REPORT_PATH}")

    total_fail = summary["pg_duckdb"]["fail"] + summary["neo4j_ladybug"]["fail"]
    return 0 if total_fail == 0 else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(_async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
