# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Pool protocol definitions for database and cache abstraction.

This module defines Protocol classes that specify the expected interface
for database connection pools and cache clients. Using Protocol enables
structural subtyping, allowing any class that implements the required
methods to satisfy the type.

All implementations MUST explicitly declare their protocol implementation
in their docstring using the "Implements:" section.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@runtime_checkable
class RelationalPool(Protocol):
    """Protocol for SQL database pools (PostgreSQL, DuckDB).

    Any class implementing these methods can be used as a RelationalPool.

    Implementations:
        - PostgresPool: PostgreSQL async pool via asyncpg/SQLAlchemy
        - DuckDBPool: DuckDB pool with asyncio.to_thread wrapper
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

    Implementations:
        - Neo4jPool: Neo4j async driver wrapper
        - LadybugPool: LadybugDB async connection wrapper
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


@runtime_checkable
class CachePool(Protocol):
    """Protocol for cache implementations (Redis, Cashews, etc.).

    Defines a unified interface for cache operations that can be
    implemented by different cache backends.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsRedisFallback: in-memory fallback using cashews
    """

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Initialize the cache connection."""
        ...

    async def shutdown(self) -> None:
        """Close the cache connection."""
        ...

    async def ping(self) -> bool:
        """Check cache connectivity.

        Returns:
            True if cache is reachable.
        """
        ...

    # ── Key/Value Operations ──────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        """Get a value by key.

        Args:
            key: Key to retrieve.

        Returns:
            Value if exists, None otherwise.
        """
        ...

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Set a key-value pair with optional TTL.

        Args:
            key: Key to set.
            value: Value to store.
            ex: Optional expiration time in seconds.
        """
        ...

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys.

        Args:
            keys: Keys to delete.

        Returns:
            Number of keys deleted.
        """
        ...

    async def expire(self, name: str, seconds: int) -> bool:
        """Set expiration on a key.

        Args:
            name: Key to set expiration on.
            seconds: Expiration time in seconds.

        Returns:
            True if key exists and expiration was set.
        """
        ...

    # ── Hash Operations ───────────────────────────────────────────────

    async def hget(self, name: str, key: str) -> str | None:
        """Get a hash field value.

        Args:
            name: Hash name.
            key: Field key.

        Returns:
            Field value if exists, None otherwise.
        """
        ...

    async def hset(self, name: str, key: str, value: str) -> None:
        """Set a hash field value.

        Args:
            name: Hash name.
            key: Field key.
            value: Field value.
        """
        ...

    async def hexists(self, name: str, key: str) -> bool:
        """Check if a hash field exists.

        Args:
            name: Hash name.
            key: Field key.

        Returns:
            True if field exists.
        """
        ...

    async def hgetall(self, name: str) -> dict[str, str]:
        """Get all fields in a hash.

        Args:
            name: Hash name.

        Returns:
            Dict of all field-value pairs.
        """
        ...

    # ── List Operations ───────────────────────────────────────────────

    async def lpush(self, name: str, *values: str) -> int:
        """Prepend values to a list.

        Args:
            name: List name.
            values: Values to prepend.

        Returns:
            New list length.
        """
        ...

    async def rpop(self, name: str) -> str | None:
        """Remove and return the last element of a list.

        Args:
            name: List name.

        Returns:
            Last element if list not empty, None otherwise.
        """
        ...

    async def llen(self, name: str) -> int:
        """Return the length of a list.

        Args:
            name: List name.

        Returns:
            List length.
        """
        ...

    # ── Sorted Set Operations ─────────────────────────────────────────

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        """Add members to a sorted set.

        Args:
            name: Sorted set name.
            mapping: Dict mapping members to scores.

        Returns:
            Number of members added.
        """
        ...

    async def zrangebyscore(
        self,
        name: str,
        min_score: float,
        max_score: float,
        start: int = 0,
        num: int = 100,
    ) -> list[str]:
        """Return members in a sorted set by score range.

        Args:
            name: Sorted set name.
            min_score: Minimum score.
            max_score: Maximum score.
            start: Offset.
            num: Maximum number of members to return.

        Returns:
            List of members in score range.
        """
        ...

    async def zrem(self, name: str, *members: str) -> int:
        """Remove members from a sorted set.

        Args:
            name: Sorted set name.
            members: Members to remove.

        Returns:
            Number of members removed.
        """
        ...

    # ── Scan Operations ───────────────────────────────────────────────

    async def scan(
        self, cursor: int = 0, match: str | None = None, count: int = 10
    ) -> tuple[int, list[str]]:
        """Scan keys incrementally.

        Args:
            cursor: Cursor position (0 to start).
            match: Pattern to match.
            count: Hint for number of keys per iteration.

        Returns:
            Tuple of (new_cursor, list of keys).
        """
        ...
