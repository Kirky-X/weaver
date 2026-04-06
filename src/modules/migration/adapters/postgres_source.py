# Copyright (c) 2026 KirkyX. All Rights Reserved
"""PostgreSQL source adapter for migration.

Implements MigrationSource protocol for reading data from PostgreSQL.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text

from modules.migration.models import ColumnDef, MigrationSchema


class PostgresSource:
    """PostgreSQL source adapter for migration.

    Implements: MigrationSource

    Reads schema and data from a PostgreSQL database for migration
    to DuckDB or other target databases.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the PostgreSQL source.

        Args:
            pool: PostgresPool instance with active connection.
        """
        self._pool = pool
        self._engine = pool.engine

    async def read_schema(self) -> list[MigrationSchema]:
        """Read schema information for all tables.

        Returns:
            List of MigrationSchema objects describing each table.
        """
        schemas = []

        async with self._engine.connect() as conn:
            # Get all user tables
            tables_result = await conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """))
            tables = [row[0] for row in tables_result.fetchall()]

            for table in tables:
                schema = await self._read_table_schema(conn, table)
                if schema:
                    schemas.append(schema)

        return schemas

    async def _read_table_schema(
        self,
        conn: Any,
        table: str,
    ) -> MigrationSchema | None:
        """Read schema for a single table."""
        # Get columns
        columns_result = await conn.execute(
            text("""
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = :table
                ORDER BY ordinal_position
            """),
            {"table": table},
        )

        columns = []
        for row in columns_result.fetchall():
            col_name, data_type, nullable, default, char_len, num_prec, num_scale = row

            # Build full type name
            full_type = data_type
            if char_len and data_type in ("character varying", "character"):
                full_type = f"{data_type}({char_len})"
            elif num_prec and num_scale and data_type == "numeric":
                full_type = f"numeric({num_prec},{num_scale})"
            elif num_prec and data_type in ("integer", "bigint"):
                pass  # No precision for integers

            columns.append(
                ColumnDef(
                    name=col_name,
                    data_type=full_type,
                    nullable=(nullable == "YES"),
                    default=default,
                )
            )

        if not columns:
            return None

        # Get primary key
        pk_result = await conn.execute(
            text("""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = :table::regclass
                AND i.indisprimary
            """),
            {"table": f"public.{table}"},
        )
        pk_row = pk_result.fetchone()
        primary_key = pk_row[0] if pk_row else columns[0].name

        # Get indexes
        idx_result = await conn.execute(
            text("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                AND tablename = :table
            """),
            {"table": table},
        )
        indexes = [row[0] for row in idx_result.fetchall()]

        return MigrationSchema(
            table=table,
            columns=columns,
            primary_key=primary_key,
            indexes=indexes,
        )

    async def read_batch(
        self,
        table: str,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read a batch of rows from a table.

        Args:
            table: Table name to read from.
            offset: Row offset for pagination.
            limit: Maximum number of rows to read.

        Returns:
            List of row dictionaries.
        """
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(f'SELECT * FROM "{table}" OFFSET :offset LIMIT :limit'),
                {"offset": offset, "limit": limit},
            )

            keys = result.keys()
            rows = []
            for row in result.fetchall():
                rows.append(dict(zip(keys, row)))

            return rows

    async def read_incremental(
        self,
        table: str,
        key: str,
        since: Any,
        limit: int = 5000,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Read rows incrementally based on a key value.

        Args:
            table: Table name to read from.
            key: Column name to use for incremental filtering.
            since: Starting value for the key column.
            limit: Batch size for each iteration.

        Yields:
            Lists of row dictionaries.
        """
        last_value = since

        while True:
            async with self._engine.connect() as conn:
                result = await conn.execute(
                    text(f"""
                        SELECT * FROM "{table}"
                        WHERE "{key}" > :last_value
                        ORDER BY "{key}"
                        LIMIT :limit
                    """),
                    {"last_value": last_value, "limit": limit},
                )

                keys = result.keys()
                rows = []
                for row in result.fetchall():
                    row_dict = dict(zip(keys, row))
                    rows.append(row_dict)
                    last_value = row_dict.get(key)

                if not rows:
                    break

                yield rows

                if len(rows) < limit:
                    break

    async def count(self, table: str) -> int:
        """Count total rows in a table.

        Args:
            table: Table name to count.

        Returns:
            Total number of rows.
        """
        async with self._engine.connect() as conn:
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            return result.scalar() or 0

    async def get_table_names(self) -> list[str]:
        """Get list of all table names."""
        async with self._engine.connect() as conn:
            result = await conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_type = 'BASE TABLE'
                """))
            return [row[0] for row in result.fetchall()]
