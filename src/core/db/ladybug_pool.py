# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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

from core.observability import get_logger
from core.utils.paths import data_path

# Global write lock for LadybugDB (only one write transaction at a time)
# LadybugDB enforces single-writer at the database level
_write_lock = asyncio.Lock()


class LadybugPool:
    """LadybugDB connection pool implementing GraphPool protocol.

    Uses real_ladybug's AsyncConnection for native async operations.

    Note: LadybugDB only supports one write transaction at a time.
    All write operations are serialized via a global lock.

    Implements:
        - GraphPool: Async graph database pool with query execution
    """

    # Default max database size: 1GB (must be power of 2 for LadybugDB)
    DEFAULT_MAX_DB_SIZE = 1 * 1024 * 1024 * 1024  # 1GB = 2^30
    # Default buffer pool size: 256MB (controls mmap allocation)
    DEFAULT_BUFFER_POOL_SIZE = 256 * 1024 * 1024  # 256MB
    # Default query timeout: 30 seconds (enforced by LadybugDB C engine)
    DEFAULT_QUERY_TIMEOUT_MS = 30_000
    # Async-level timeout for query execution (secondary defense when
    # set_query_timeout doesn't work or real_ladybug swallows CancelledError)
    ASYNC_QUERY_TIMEOUT_SECONDS = 30.0
    # Max concurrent queries (connections + threads). Default is 4, but we
    # increase to 16 to prevent pool exhaustion when queries hang.
    MAX_CONCURRENT_QUERIES = 16

    @property
    def database_type(self) -> str:
        """Return the database type identifier.

        Implements: GraphPool.database_type
        """
        return "ladybug"

    def __init__(
        self,
        db_path: str = data_path("weaver.lbug"),
        max_db_size: int | None = None,
        buffer_pool_size: int | None = None,
    ):
        self._db_path = db_path
        self._max_db_size = max_db_size or self.DEFAULT_MAX_DB_SIZE
        self._buffer_pool_size = buffer_pool_size or self.DEFAULT_BUFFER_POOL_SIZE
        self._db: ladybug.Database | None = None
        self._conn: ladybug.AsyncConnection | None = None

    async def startup(self) -> None:
        """Initialize the LadybugDB connection."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = ladybug.Database(
            self._db_path,
            max_db_size=self._max_db_size,
            buffer_pool_size=self._buffer_pool_size,
        )
        # Increase max_concurrent_queries to prevent pool exhaustion
        self._conn = ladybug.AsyncConnection(
            self._db, max_concurrent_queries=self.MAX_CONCURRENT_QUERIES
        )
        # Set query timeout at connection level (enforced by C engine).
        # This is the primary defense against hung queries.
        self._conn.set_query_timeout(self.DEFAULT_QUERY_TIMEOUT_MS)

    def startup_sync(self) -> None:
        """Initialize the LadybugDB connection (sync version for fallback use)."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = ladybug.Database(
            self._db_path,
            max_db_size=self._max_db_size,
            buffer_pool_size=self._buffer_pool_size,
        )
        self._conn = ladybug.AsyncConnection(
            self._db, max_concurrent_queries=self.MAX_CONCURRENT_QUERIES
        )
        self._conn.set_query_timeout(self.DEFAULT_QUERY_TIMEOUT_MS)

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
        """Internal query execution without lock.

        Uses asyncio.wait with timeout as secondary defense against hung queries.
        The primary defense is set_query_timeout() called during startup.

        Note: real_ladybug's AsyncConnection.execute catches CancelledError
        without re-raising, making asyncio.wait_for ineffective. asyncio.wait
        with timeout returns control without relying on CancelledError propagation.

        Important: We do NOT call task.cancel() after timeout because
        real_ladybug's CancelledError handler calls conn.interrupt() which
        may block the event loop. We also do NOT call _interrupt_all_connections()
        because conn.interrupt() may cause deadlock. Instead, we rely on
        set_query_timeout() (enforced by C engine) to kill hung queries.
        """
        loop = asyncio.get_running_loop()
        # Run the entire query execution and result fetching in a thread
        # to avoid any blocking C calls from blocking the event loop.
        task = asyncio.ensure_future(
            loop.run_in_executor(
                self._conn.executor,
                self._execute_and_fetch,
                query,
                parameters,
            )
        )
        _done, pending = await asyncio.wait({task}, timeout=self.ASYNC_QUERY_TIMEOUT_SECONDS)

        if task in pending:
            # Task is still running after timeout.
            # Do NOT call task.cancel() — real_ladybug's CancelledError handler
            # calls conn.interrupt() which may block the event loop.
            # Do NOT call _interrupt_all_connections() — conn.interrupt() may
            # cause deadlock. Rely on set_query_timeout() to kill the query.
            log = get_logger(__name__)
            log.warning(
                "ladybug_query_timeout",
                timeout_seconds=self.ASYNC_QUERY_TIMEOUT_SECONDS,
                query_preview=query[:200],
            )
            raise TimeoutError(
                f"LadybugDB query timed out after "
                f"{self.ASYNC_QUERY_TIMEOUT_SECONDS}s: {query[:200]}"
            )

        # Task completed — get result (may raise if task failed)
        return task.result()

    def _execute_and_fetch(self, query: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute query and fetch all results (runs in thread pool).

        This method uses a synchronous Connection directly (not AsyncConnection)
        to avoid the connection pool counter issues. The Connection is acquired
        from the AsyncConnection's pool and released after use.
        """
        conn = self._conn.acquire_connection()
        try:
            result = conn.execute(query, parameters)
            rows: list[dict[str, Any]] = []
            while result.has_next():
                row = result.get_next()
                column_names = result.get_column_names()
                rows.append(dict(zip(column_names, row)))
            return rows
        finally:
            self._conn.release_connection(conn)

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
