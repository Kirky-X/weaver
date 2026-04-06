# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB source adapter for migration.

Implements MigrationSource protocol for reading data from DuckDB.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text

from modules.migration.models import ColumnDef, MigrationSchema


class DuckDBSource:
    """DuckDB source adapter for migration.

    Implements: MigrationSource

    Reads schema and data from a DuckDB database for migration
    to PostgreSQL or other target databases.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the DuckDB source.

        Args:
            pool: DuckDBPool instance with active connection.
        """
        self._pool = pool
        self._engine = pool._engine

    async def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a sync function in a thread."""
        return await asyncio.to_thread(func, *args, **kwargs)

    async def read_schema(self) -> list[MigrationSchema]:
        """Read schema information for all tables.

        Returns:
            List of MigrationSchema objects describing each table.
        """
        schemas = []

        def _read_schema_sync() -> list[MigrationSchema]:
            result = []
            with self._engine.connect() as conn:
                # Get all tables
                tables_result = conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'main'
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """))
                tables = [row[0] for row in tables_result.fetchall()]

                for table in tables:
                    schema = self._read_table_schema_sync(conn, table)
                    if schema:
                        result.append(schema)

            return result

        schemas = await self._run_sync(_read_schema_sync)
        return schemas

    def _read_table_schema_sync(self, conn: Any, table: str) -> MigrationSchema | None:
        """Read schema for a single table (sync)."""
        columns_result = conn.execute(
            text("""
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = 'main'
                AND table_name = :table
                ORDER BY ordinal_position
            """),
            {"table": table},
        )

        columns = []
        for row in columns_result.fetchall():
            col_name, data_type, nullable, default = row
            columns.append(
                ColumnDef(
                    name=col_name,
                    data_type=data_type,
                    nullable=(nullable == "YES"),
                    default=default,
                )
            )

        if not columns:
            return None

        # DuckDB doesn't have explicit primary key in information_schema
        # Use first column or look for 'id' column
        primary_key = columns[0].name
        for col in columns:
            if col.name.lower() == "id":
                primary_key = col.name
                break

        return MigrationSchema(
            table=table,
            columns=columns,
            primary_key=primary_key,
            indexes=[],
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

        def _read_batch_sync() -> list[dict[str, Any]]:
            with self._engine.connect() as conn:
                result = conn.execute(
                    text(f'SELECT * FROM "{table}" OFFSET :offset LIMIT :limit'),
                    {"offset": offset, "limit": limit},
                )

                keys = result.keys()
                rows = []
                for row in result.fetchall():
                    rows.append(dict(zip(keys, row)))

                return rows

        return await self._run_sync(_read_batch_sync)

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

            def _read_incremental_sync() -> list[dict[str, Any]]:
                with self._engine.connect() as conn:
                    result = conn.execute(
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

                    return rows

            rows = await self._run_sync(_read_incremental_sync)

            if not rows:
                break

            last_value = rows[-1].get(key)
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

        def _count_sync() -> int:
            with self._engine.connect() as conn:
                result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                return result.scalar() or 0

        return await self._run_sync(_count_sync)

    async def get_table_names(self) -> list[str]:
        """Get list of all table names."""

        def _get_tables_sync() -> list[str]:
            with self._engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'main'
                    AND table_type = 'BASE TABLE'
                """))
                return [row[0] for row in result.fetchall()]

        return await self._run_sync(_get_tables_sync)
