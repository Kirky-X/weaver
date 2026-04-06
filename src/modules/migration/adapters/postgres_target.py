# Copyright (c) 2026 KirkyX. All Rights Reserved
"""PostgreSQL target adapter for migration.

Implements MigrationTarget protocol for writing data to PostgreSQL.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import MigrationSchema


class PostgresTarget:
    """PostgreSQL target adapter for migration.

    Implements: MigrationTarget

    Writes data to a PostgreSQL database during migration.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the PostgreSQL target.

        Args:
            pool: PostgresPool instance with active connection.
        """
        self._pool = pool
        self._engine = pool.engine

    async def ensure_schema(self, schema: MigrationSchema) -> None:
        """Ensure the target table exists with correct schema.

        Creates the table if it doesn't exist. Adds missing columns if needed.

        Args:
            schema: Schema definition for the table.
        """
        async with self._engine.begin() as conn:
            # Check if table exists
            exists_result = await conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = :table
                    )
                """),
                {"table": schema.table},
            )
            exists = exists_result.scalar()

            if not exists:
                # Create table
                await self._create_table(conn, schema)
            else:
                # Ensure columns exist
                await self._ensure_columns(conn, schema)

    async def _create_table(self, conn: Any, schema: MigrationSchema) -> None:
        """Create a new table from schema."""
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

        await conn.execute(text(create_sql))

        # Create indexes
        for idx_name in schema.indexes:
            try:
                await conn.execute(
                    text(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{schema.table}"')
                )
            except Exception:
                pass  # Index might already exist or have different definition

    async def _ensure_columns(self, conn: Any, schema: MigrationSchema) -> None:
        """Ensure all columns exist in the table."""
        for col in schema.columns:
            # Check if column exists
            col_result = await conn.execute(
                text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = :table
                    AND column_name = :column
                """),
                {"table": schema.table, "column": col.name},
            )

            if not col_result.fetchone():
                # Add missing column
                col_def = f'"{col.name}" {col.data_type}'
                if col.default is not None:
                    col_def += f" DEFAULT {col.default}"

                await conn.execute(
                    text(f'ALTER TABLE "{schema.table}" ADD COLUMN {col_def}'),
                )

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Write a batch of rows to a table.

        Uses INSERT ... ON CONFLICT DO UPDATE for upsert behavior.

        Args:
            table: Target table name.
            rows: List of row dictionaries to write.

        Returns:
            Number of rows successfully written.
        """
        if not rows:
            return 0

        # Get column names from first row
        columns = list(rows[0].keys())
        col_names = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(f":{c}" for c in columns)

        # Get primary key for conflict resolution
        # We'll use the first column as a simple default
        pk = columns[0]
        update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columns if c != pk)

        if update_set:
            sql = text(f"""
                INSERT INTO "{table}" ({col_names})
                VALUES ({placeholders})
                ON CONFLICT ("{pk}") DO UPDATE SET {update_set}
            """)
        else:
            sql = text(f"""
                INSERT INTO "{table}" ({col_names})
                VALUES ({placeholders})
                ON CONFLICT ("{pk}") DO NOTHING
            """)

        written = 0
        async with self._engine.begin() as conn:
            for row in rows:
                try:
                    await conn.execute(sql, row)
                    written += 1
                except Exception:
                    # Log and continue on individual row errors
                    pass

        return written

    async def verify(self, table: str, expected_count: int) -> bool:
        """Verify migration completed successfully.

        Args:
            table: Table name to verify.
            expected_count: Expected number of rows.

        Returns:
            True if verification passed.
        """
        async with self._engine.connect() as conn:
            result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            actual_count = result.scalar() or 0

            if actual_count < expected_count:
                raise ValidationFailedError(
                    table=table,
                    expected=expected_count,
                    actual=actual_count,
                )

            return True

    async def truncate(self, table: str) -> None:
        """Truncate a table (for clean migration restart)."""
        async with self._engine.begin() as conn:
            await conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
