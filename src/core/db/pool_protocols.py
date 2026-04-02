# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pool protocol definitions for database abstraction.

This module defines Protocol classes that specify the expected interface
for database connection pools. Using Protocol enables structural subtyping,
allowing any class that implements the required methods to satisfy the type.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@runtime_checkable
class RelationalPool(Protocol):
    """Protocol for SQL database pools (PostgreSQL, DuckDB).

    Any class implementing these methods can be used as a RelationalPool.
    """

    async def startup(self) -> None:
        """Initialize the pool."""
        ...

    async def shutdown(self) -> None:
        """Close the pool and release resources."""
        ...

    @property
    def engine(self) -> AsyncEngine:
        """Return the async engine.

        Raises:
            RuntimeError: If pool has not been started.
        """
        ...

    def session(self) -> AsyncSession:
        """Create a new async session.

        Returns:
            A new AsyncSession instance.

        Raises:
            RuntimeError: If pool has not been started.
        """
        ...

    async def session_context(self) -> AsyncIterator[AsyncSession]:
        """Context manager for database sessions with automatic cleanup.

        Yields:
            AsyncSession instance.
        """
        ...


@runtime_checkable
class GraphPool(Protocol):
    """Protocol for graph database pools (Neo4j, LadybugDB).

    Any class implementing these methods can be used as a GraphPool.
    """

    async def startup(self) -> None:
        """Initialize the pool."""
        ...

    async def shutdown(self) -> None:
        """Close the pool and release resources."""
        ...

    async def execute_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query and return results as list of dicts.

        Args:
            query: Query string (SQL or Cypher).
            parameters: Optional query parameters.

        Returns:
            List of result records as dictionaries.
        """
        ...

    async def session_context(self) -> AsyncIterator[Any]:
        """Context manager for sessions with automatic cleanup.

        Yields:
            Session instance (type depends on implementation).
        """
        ...
