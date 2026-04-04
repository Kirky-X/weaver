# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB connection pool implementing GraphPool protocol.

LadybugDB provides native async support via AsyncConnection.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import real_ladybug as ladybug

# Global write lock for LadybugDB (only one write transaction at a time)
# LadybugDB enforces single-writer at the database level
_write_lock = asyncio.Lock()


class LadybugPool:
    """LadybugDB connection pool implementing GraphPool protocol.

    Uses real_ladybug's AsyncConnection for native async operations.

    Note: LadybugDB only supports one write transaction at a time.
    All write operations are serialized via a global lock.
    """

    def __init__(self, db_path: str = "data/weaver_graph.ladybug"):
        self._db_path = db_path
        self._db: ladybug.Database | None = None
        self._conn: ladybug.AsyncConnection | None = None

    async def startup(self) -> None:
        """Initialize the LadybugDB connection."""
        # Create data directory
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Create Database and AsyncConnection
        self._db = ladybug.Database(self._db_path)
        self._conn = ladybug.AsyncConnection(self._db)

    async def shutdown(self) -> None:
        """Close the connection.

        Note: LadybugDB doesn't require explicit close for basic usage.
        """
        # LadybugDB handles cleanup internally
        self._conn = None
        self._db = None

    async def execute_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query and return results as list of dicts.

        Serializes write operations via a global lock because LadybugDB
        only supports one write transaction at a time.

        Args:
            query: Query string.
            parameters: Optional query parameters.

        Returns:
            List of result records as dictionaries.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._conn is None:
            raise RuntimeError("LadybugPool not started")

        # Detect if this is a write query
        is_write = any(
            kw in query.upper() for kw in ["CREATE", "MERGE", "SET", "DELETE", "INSERT", "UPDATE"]
        )

        if is_write:
            # Serialize write operations
            async with _write_lock:
                return await self._execute_query_internal(query, parameters or {})
        else:
            # Read queries can run in parallel
            return await self._execute_query_internal(query, parameters or {})

    async def _execute_query_internal(
        self, query: str, parameters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Internal query execution without lock."""
        result = await self._conn.execute(query, parameters)
        rows: list[dict[str, Any]] = []

        while result.has_next():
            row = result.get_next()
            column_names = result.get_column_names()
            rows.append(dict(zip(column_names, row)))

        return rows

    @asynccontextmanager
    async def session_context(self) -> AsyncIterator[ladybug.AsyncConnection]:
        """Context manager for sessions with automatic cleanup.

        Yields:
            AsyncConnection instance.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._conn is None:
            raise RuntimeError("LadybugPool not started")
        yield self._conn
