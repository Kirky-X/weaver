# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB connection pool implementing RelationalPool protocol.

DuckDB doesn't support native async, so this implementation wraps a sync
SQLAlchemy engine with asyncio.to_thread for async compatibility.

For :memory: mode, all sessions share the same underlying connection
to ensure they access the same in-memory database.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session

from core.observability.logging import get_logger

log = get_logger(__name__)


class _DuckDBAsyncSession:
    """Wraps sync Session to provide AsyncSession-compatible interface.

    DuckDB doesn't support async operations, so this wrapper uses
    asyncio.to_thread to execute sync operations in a background thread.

    Implements async context manager protocol for compatibility with
    code that uses `async with session() as session:`.
    """

    def __init__(self, sync_session: Session):
        self._sync_session = sync_session

    async def __aenter__(self) -> _DuckDBAsyncSession:
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Exit async context manager with automatic commit/rollback."""
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()
        await self.close()

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        """Execute a statement asynchronously."""
        return await asyncio.to_thread(self._sync_session.execute, statement, params or {})

    async def scalars(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        """Execute statement and return scalar results."""
        return await asyncio.to_thread(self._sync_session.scalars, statement, params or {})

    async def scalar(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        """Execute statement and return single scalar result."""
        return await asyncio.to_thread(self._sync_session.scalar, statement, params or {})

    async def commit(self) -> None:
        """Commit the transaction."""
        await asyncio.to_thread(self._sync_session.commit)

    async def rollback(self) -> None:
        """Rollback the transaction."""
        await asyncio.to_thread(self._sync_session.rollback)

    async def close(self) -> None:
        """Close the session."""
        await asyncio.to_thread(self._sync_session.close)

    async def flush(self) -> None:
        """Flush pending changes to database."""
        await asyncio.to_thread(self._sync_session.flush)

    async def refresh(self, instance: Any) -> None:
        """Refresh an instance from database."""
        await asyncio.to_thread(self._sync_session.refresh, instance)

    def add(self, instance: Any) -> None:
        """Add an instance to the session (sync, no IO)."""
        self._sync_session.add(instance)

    def add_all(self, instances: list[Any]) -> None:
        """Add multiple instances to the session (sync, no IO)."""
        self._sync_session.add_all(instances)

    def delete(self, instance: Any) -> None:
        """Delete an instance from the session (sync, no IO)."""
        self._sync_session.delete(instance)

    async def get(self, entity: type[Any], ident: Any) -> Any | None:
        """Get an entity by identity."""
        return await asyncio.to_thread(self._sync_session.get, entity, ident)


class DuckDBPool:
    """DuckDB connection pool implementing RelationalPool protocol.

    Uses sync SQLAlchemy engine with asyncio.to_thread wrapper for async ops.

    For :memory: databases, uses a single shared connection to ensure
    all sessions see the same data (DuckDB :memory: is connection-isolated).

    Implements:
        - RelationalPool: Async SQL database pool with session management
    """

    def __init__(self, db_path: str = "data/weaver.duckdb"):
        self._db_path = db_path
        self._is_memory = db_path == ":memory:"
        self._engine: Engine | None = None
        self._async_engine: AsyncEngine | None = None
        # For :memory: mode, shared connection used by all sessions
        self._shared_connection: Any = None

    async def startup(self) -> None:
        """Initialize the DuckDB engine."""
        # Create data directory (only for file-based databases)
        if not self._is_memory:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Standard DuckDB URL
        db_url = f"duckdb:///{self._db_path}"

        # Create sync engine
        def _create_engine() -> Engine:
            return create_engine(
                db_url,
                echo=False,
                future=True,
            )

        loop = asyncio.get_event_loop()
        self._engine = await loop.run_in_executor(None, _create_engine)

        # For :memory:, create a single shared connection that all sessions will use
        # This ensures all sessions see the same in-memory database
        if self._is_memory:

            def _get_connection():
                return self._engine.connect()

            self._shared_connection = await loop.run_in_executor(None, _get_connection)

    async def shutdown(self) -> None:
        """Close the engine and shared connection."""
        if self._shared_connection is not None:
            await asyncio.to_thread(self._shared_connection.close)
            self._shared_connection = None
        if self._engine is not None:
            await asyncio.to_thread(self._engine.dispose)
            self._engine = None

    @property
    def engine(self) -> AsyncEngine:
        """Return the engine wrapped as AsyncEngine-compatible.

        Note: Returns a wrapper since DuckDB doesn't have true async engine.
        For direct engine access, use _sync_engine property.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._engine is None:
            raise RuntimeError("DuckDBPool not started")
        return self._async_engine  # type: ignore

    def session(self) -> _DuckDBAsyncSession:
        """Create a new async-compatible session.

        For :memory: mode, all sessions share the same underlying connection
        to ensure they access the same in-memory database.

        Returns:
            A new _DuckDBAsyncSession instance wrapping a sync Session.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._engine is None:
            raise RuntimeError("DuckDBPool not started")

        # For :memory: mode, bind session to shared connection
        if self._is_memory and self._shared_connection is not None:
            sync_session = Session(bind=self._shared_connection, expire_on_commit=False)
        else:
            sync_session = Session(self._engine, expire_on_commit=False)
        return _DuckDBAsyncSession(sync_session)

    @asynccontextmanager
    async def session_context(self) -> AsyncIterator[_DuckDBAsyncSession]:
        """Context manager for database sessions with automatic cleanup.

        Yields:
            _DuckDBAsyncSession instance.
        """
        session = self.session()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
