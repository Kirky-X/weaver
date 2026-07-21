# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for DuckDB schema BIGINT_PK_TABLES mapping and _reset_duckdb_sequences.

Covers R-duckdb-schema-004 (BIGINT_PK_TABLES mapping completeness) and
R-duckdb-schema-005 (sequence reset behavior).

Uses in-memory DuckDB to verify:
1. Every <table> → <sequence> mapping in BIGINT_PK_TABLES points to an
   existing table and an existing sequence.
2. _reset_duckdb_sequences (called inside initialize_duckdb_schema) correctly
   resets sequence START to MAX(id)+1 for tables with data, and leaves empty
   tables at START=1.
"""

# ruff: noqa: S608 — All f-string SQL in this file uses table/seq_name from
# BIGINT_PK_TABLES module-level constant dict; no user-input pollution path.

from __future__ import annotations

import pytest
from sqlalchemy import text

from core.db.duckdb_schema import BIGINT_PK_TABLES, SEQUENCE_QUERIES


@pytest.fixture
async def in_memory_duckdb_pool():
    """In-memory DuckDB pool with full schema initialized."""
    from core.db.duckdb_pool import DuckDBPool
    from core.db.duckdb_schema import initialize_duckdb_schema

    pool = DuckDBPool(db_path=":memory:")
    await pool.startup()
    try:
        await initialize_duckdb_schema(pool)
        yield pool
    finally:
        await pool.shutdown()


class TestBigIntPkTablesMapping:
    """Verify BIGINT_PK_TABLES mapping integrity (R-duckdb-schema-004)."""

    @pytest.mark.parametrize(
        "table_name,seq_name",
        sorted(BIGINT_PK_TABLES.items()),
        ids=[f"{t}->{s}" for t, s in sorted(BIGINT_PK_TABLES.items())],
    )
    @pytest.mark.asyncio
    async def test_table_exists_in_memory(self, table_name, seq_name, in_memory_duckdb_pool):
        """Each table in BIGINT_PK_TABLES must exist in in-memory DuckDB."""
        async with in_memory_duckdb_pool.session() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'main' AND table_name = :name"
                ),
                {"name": table_name},
            )
            count = result.scalar()
            assert count == 1, (
                f"Table '{table_name}' (mapped to sequence '{seq_name}') "
                f"does not exist in DuckDB schema"
            )

    @pytest.mark.parametrize(
        "table_name,seq_name",
        sorted(BIGINT_PK_TABLES.items()),
        ids=[f"{t}->{s}" for t, s in sorted(BIGINT_PK_TABLES.items())],
    )
    @pytest.mark.asyncio
    async def test_sequence_exists_in_memory(self, table_name, seq_name, in_memory_duckdb_pool):
        """Each sequence in BIGINT_PK_TABLES must exist in in-memory DuckDB."""
        async with in_memory_duckdb_pool.session() as session:
            result = await session.execute(text(f"SELECT nextval('{seq_name}')"))
            value = result.scalar()
            assert value is not None, (
                f"Sequence '{seq_name}' (mapped to table '{table_name}') "
                f"does not exist or returned NULL"
            )

    @pytest.mark.parametrize(
        "table_name,seq_name",
        sorted(BIGINT_PK_TABLES.items()),
        ids=[f"{t}->{s}" for t, s in sorted(BIGINT_PK_TABLES.items())],
    )
    @pytest.mark.asyncio
    async def test_table_id_column_has_default_nextval(
        self, table_name, seq_name, in_memory_duckdb_pool
    ):
        """Each table's 'id' column must default to nextval('<seq_name>')."""
        async with in_memory_duckdb_pool.session() as session:
            result = await session.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = 'id'"
                ),
                {"table": table_name},
            )
            column_default = result.scalar()

        assert column_default is not None, (
            f"Table '{table_name}' id column has no default; expected nextval('{seq_name}')"
        )
        # DuckDB stores default as "nextval('seq_name')" or similar
        assert seq_name in str(column_default), (
            f"Table '{table_name}' id column default '{column_default}' "
            f"does not reference sequence '{seq_name}'"
        )

    @pytest.mark.asyncio
    async def test_bigint_pk_tables_count_matches_sequence_queries(self, in_memory_duckdb_pool):
        """BIGINT_PK_TABLES size should be <= SEQUENCE_QUERIES size (some sequences may be unused)."""
        # All sequences referenced in BIGINT_PK_TABLES must exist in SEQUENCE_QUERIES
        import re

        seq_names_in_queries: set[str] = set()
        for q in SEQUENCE_QUERIES:
            match = re.search(r"CREATE\s+SEQUENCE\s+IF\s+NOT\s+EXISTS\s+(\w+)", q, re.IGNORECASE)
            if match:
                seq_names_in_queries.add(match.group(1))
        seq_names_in_mapping = set(BIGINT_PK_TABLES.values())

        missing = seq_names_in_mapping - seq_names_in_queries
        assert not missing, (
            f"Sequences referenced in BIGINT_PK_TABLES but missing from SEQUENCE_QUERIES: "
            f"{sorted(missing)}"
        )


class TestResetDuckDBSequences:
    """Verify _reset_duckdb_sequences behavior (R-duckdb-schema-005).

    The reset logic is invoked inside initialize_duckdb_schema (F-007 fix).
    For each BIGINT_PK_TABLES entry:
      - empty table → sequence START remains at 1 (no reset needed)
      - table with data → sequence START = MAX(id) + 1
    """

    @pytest.mark.asyncio
    async def test_empty_table_sequence_starts_at_1(self, in_memory_duckdb_pool):
        """Empty table's sequence must return 1 on first nextval."""
        # Pick a table that's empty after schema init (e.g., api_keys)
        table = "api_keys"
        seq_name = BIGINT_PK_TABLES[table]

        async with in_memory_duckdb_pool.session() as session:
            # Verify table is empty
            count_result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            assert count_result.scalar() == 0, f"Test setup error: {table} should be empty"

            # Sequence should be at START 1
            result = await session.execute(text(f"SELECT nextval('{seq_name}')"))
            first_val = result.scalar()
            assert first_val == 1, (
                f"Empty table {table} sequence {seq_name} first nextval = {first_val}, expected 1"
            )

    @pytest.mark.asyncio
    async def test_reset_sequence_after_insert_sets_start_to_max_plus_one(
        self, in_memory_duckdb_pool
    ):
        """After inserting rows with id=10..14, _reset_duckdb_sequences must
        set sequence START to 15 (MAX(id)+1).

        This simulates the F-007 scenario: PG→DuckDB import copies id values
        but DuckDB sequence remains at START 1. _reset_duckdb_sequences (called
        by initialize_duckdb_schema) must advance the sequence past MAX(id).
        """
        table = "api_keys"
        seq_name = BIGINT_PK_TABLES[table]

        async with in_memory_duckdb_pool.session() as session:
            # Insert 5 rows with explicit id values (simulating PG→DuckDB import)
            for i in range(10, 15):
                # api_keys schema: id, key_id, key_hash, scopes, rate_limit_per_min,
                # expires_at, last_used_at, is_revoked, rotated_to, created_by, created_at
                await session.execute(
                    text(
                        f"INSERT INTO {table} (id, key_id, key_hash, scopes, "
                        f"rate_limit_per_min, is_revoked, created_by) "
                        f"VALUES (:id, :key_id, :key_hash, :scopes, "
                        f":rate_limit, :is_revoked, :created_by)"
                    ),
                    {
                        "id": i,
                        "key_id": f"test_key_{i}",
                        "key_hash": f"hash_{i}",
                        "scopes": '["read"]',
                        "rate_limit": 60,
                        "is_revoked": False,
                        "created_by": "test",
                    },
                )
            await session.commit()

            # Verify MAX(id) == 14
            max_result = await session.execute(text(f"SELECT MAX(id) FROM {table}"))
            max_id = max_result.scalar()
            assert max_id == 14, f"Test setup error: MAX(id) = {max_id}, expected 14"

        # Now call initialize_duckdb_schema again to trigger _reset_duckdb_sequences
        from core.db.duckdb_schema import initialize_duckdb_schema

        await initialize_duckdb_schema(in_memory_duckdb_pool)

        # Verify next nextval returns 15 (MAX(id) + 1)
        async with in_memory_duckdb_pool.session() as session:
            result = await session.execute(text(f"SELECT nextval('{seq_name}')"))
            next_val = result.scalar()
            assert next_val == 15, (
                f"After reset, {table} sequence {seq_name} nextval = {next_val}, "
                f"expected 15 (MAX(id)=14 + 1)"
            )

    @pytest.mark.asyncio
    async def test_reset_does_not_lose_table_data(self, in_memory_duckdb_pool):
        """_reset_duckdb_sequences must not delete or modify table data."""
        table = "api_keys"

        async with in_memory_duckdb_pool.session() as session:
            # Insert 3 rows
            for i in range(20, 23):
                await session.execute(
                    text(
                        f"INSERT INTO {table} (id, key_id, key_hash, scopes, "
                        f"rate_limit_per_min, is_revoked, created_by) "
                        f"VALUES (:id, :key_id, :key_hash, :scopes, "
                        f":rate_limit, :is_revoked, :created_by)"
                    ),
                    {
                        "id": i,
                        "key_id": f"keep_key_{i}",
                        "key_hash": f"keep_hash_{i}",
                        "scopes": '["read"]',
                        "rate_limit": 60,
                        "is_revoked": False,
                        "created_by": "test",
                    },
                )
            await session.commit()
            pre_count_result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            pre_count = pre_count_result.scalar()
            assert pre_count == 3, f"Test setup error: pre-reset count = {pre_count}"

        # Trigger reset
        from core.db.duckdb_schema import initialize_duckdb_schema

        await initialize_duckdb_schema(in_memory_duckdb_pool)

        async with in_memory_duckdb_pool.session() as session:
            post_count_result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            post_count = post_count_result.scalar()

        assert post_count == pre_count, (
            f"Reset changed data: pre={pre_count}, post={post_count}. "
            f"Data loss occurred during _reset_duckdb_sequences."
        )

    @pytest.mark.asyncio
    async def test_reset_skips_empty_tables(self, in_memory_duckdb_pool):
        """_reset_duckdb_sequences must skip empty tables (MAX(id) IS NULL → no-op)."""
        # Pick an empty table after schema init
        table = "alert_rules"
        seq_name = BIGINT_PK_TABLES[table]

        async with in_memory_duckdb_pool.session() as session:
            # Confirm empty
            count_result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            assert count_result.scalar() == 0

            # Get current nextval (should be 1)
            result1 = await session.execute(text(f"SELECT nextval('{seq_name}')"))
            val1 = result1.scalar()

        # Trigger reset
        from core.db.duckdb_schema import initialize_duckdb_schema

        await initialize_duckdb_schema(in_memory_duckdb_pool)

        # Verify sequence still advances naturally (not reset to a lower value)
        async with in_memory_duckdb_pool.session() as session:
            result2 = await session.execute(text(f"SELECT nextval('{seq_name}')"))
            val2 = result2.scalar()

        # val2 should be val1 + 1 (no reset happened, sequence continues)
        assert val2 == val1 + 1, (
            f"Empty table sequence was reset unexpectedly: "
            f"val1={val1}, val2={val2} (expected {val1 + 1})"
        )
