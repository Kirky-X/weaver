# Copyright (c) 2026 KirkyX. All Rights Reserved
"""DuckDB connection pool implementing RelationalPool protocol.

DuckDB doesn't support native async, so this implementation wraps a sync
SQLAlchemy engine with asyncio.to_thread for async compatibility.
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

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
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

    Implements:
        - RelationalPool: Async SQL database pool with session management
    """

    def __init__(self, db_path: str = "data/weaver.duckdb"):
        self._db_path = db_path
        self._engine: Engine | None = None
        self._async_engine: AsyncEngine | None = None

    async def startup(self) -> None:
        """Initialize the DuckDB engine."""
        # Create data directory
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # Create sync engine in thread pool to avoid blocking
        def _create_engine() -> Engine:
            return create_engine(
                f"duckdb:///{self._db_path}",
                echo=False,
                future=True,
            )

        loop = asyncio.get_event_loop()
        self._engine = await loop.run_in_executor(None, _create_engine)

    async def shutdown(self) -> None:
        """Close the engine."""
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
        # DuckDB doesn't have real AsyncEngine, return wrapper behavior
        # Users should use session() or session_context() for proper async ops
        return self._async_engine  # type: ignore

    def session(self) -> _DuckDBAsyncSession:
        """Create a new async-compatible session.

        Returns:
            A new _DuckDBAsyncSession instance wrapping a sync Session.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._engine is None:
            raise RuntimeError("DuckDBPool not started")
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
