# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB target adapter for migration.

Implements MigrationTarget protocol for writing data to DuckDB.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text

from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import MigrationSchema


class DuckDBTarget:
    """DuckDB target adapter for migration.

    Implements: MigrationTarget

    Writes data to a DuckDB database during migration.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the DuckDB target.

        Args:
            pool: DuckDBPool instance with active connection.
        """
        self._pool = pool
        self._engine = pool._engine

    async def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a sync function in a thread."""
        return await asyncio.to_thread(func, *args, **kwargs)

    async def ensure_schema(self, schema: MigrationSchema) -> None:
        """Ensure the target table exists with correct schema.

        Creates the table if it doesn't exist. Adds missing columns if needed.

        Args:
            schema: Schema definition for the table.
        """

        def _ensure_schema_sync() -> None:
            with self._engine.begin() as conn:
                # Check if table exists
                exists_result = conn.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'main'
                            AND table_name = :table
                        )
                    """),
                    {"table": schema.table},
                )
                exists = exists_result.scalar()

                if not exists:
                    self._create_table_sync(conn, schema)
                else:
                    self._ensure_columns_sync(conn, schema)

        await self._run_sync(_ensure_schema_sync)

    def _create_table_sync(self, conn: Any, schema: MigrationSchema) -> None:
        """Create a new table from schema (sync)."""
        columns_sql = []
        for col in schema.columns:
            col_def = f'"{col.name}" {col.data_type}'
            if not col.nullable:
                col_def += " NOT NULL"
            if col.default is not None:
                col_def += f" DEFAULT {col.default}"
            columns_sql.append(col_def)

        # Add primary key constraint
        columns_sql.append(f'PRIMARY KEY ("{schema.primary_key}")')

        create_sql = f"""
            CREATE TABLE IF NOT EXISTS "{schema.table}" (
                {", ".join(columns_sql)}
            )
        """

        conn.execute(text(create_sql))

    def _ensure_columns_sync(self, conn: Any, schema: MigrationSchema) -> None:
        """Ensure all columns exist in the table (sync)."""
        for col in schema.columns:
            col_result = conn.execute(
                text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'main'
                    AND table_name = :table
                    AND column_name = :column
                """),
                {"table": schema.table, "column": col.name},
            )

            if not col_result.fetchone():
                col_def = f'"{col.name}" {col.data_type}'
                if col.default is not None:
                    col_def += f" DEFAULT {col.default}"

                conn.execute(
                    text(f'ALTER TABLE "{schema.table}" ADD COLUMN {col_def}'),
                )

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Write a batch of rows to a table.

        Uses INSERT OR REPLACE for upsert behavior.

        Args:
            table: Target table name.
            rows: List of row dictionaries to write.

        Returns:
            Number of rows successfully written.
        """
        if not rows:
            return 0

        columns = list(rows[0].keys())
        col_names = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f":{c}" for c in columns)

        # DuckDB uses INSERT OR REPLACE
        # Table names come from migration config, not user input
        sql = text(f"""
            INSERT OR REPLACE INTO "{table}" ({col_names})
            VALUES ({placeholders})
        """)

        def _write_batch_sync() -> int:
            written = 0
            with self._engine.begin() as conn:
                for row in rows:
                    try:
                        conn.execute(sql, row)
                        written += 1
                    except Exception:
                        pass
            return written

        return await self._run_sync(_write_batch_sync)

    async def verify(self, table: str, expected_count: int) -> bool:
        """Verify migration completed successfully.

        Args:
            table: Table name to verify.
            expected_count: Expected number of rows.

        Returns:
            True if verification passed.
        """

        def _verify_sync() -> int:
            with self._engine.connect() as conn:
                result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                return result.scalar() or 0

        actual_count = await self._run_sync(_verify_sync)

        if actual_count < expected_count:
            raise ValidationFailedError(
                table=table,
                expected=expected_count,
                actual=actual_count,
            )

        return True

    async def truncate(self, table: str) -> None:
        """Truncate a table (for clean migration restart)."""

        def _truncate_sync() -> None:
            with self._engine.begin() as conn:
                conn.execute(text(f'DELETE FROM "{table}"'))

        await self._run_sync(_truncate_sync)
