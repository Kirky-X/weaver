# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
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
class CacheKV(Protocol):
    """Protocol for key/value cache operations.

    Defines basic key-value operations supported by cache backends.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsClient: in-memory cache client using cashews
        - FallbackCachePool: Redis→Cashews degradation proxy
    """

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

    async def mget(self, keys: list[str]) -> list[str | None]:
        """Get multiple values by keys.

        Args:
            keys: List of keys to retrieve.

        Returns:
            List of values (None for missing keys).
        """
        ...


@runtime_checkable
class CacheHash(Protocol):
    """Protocol for hash cache operations.

    Defines hash data structure operations supported by cache backends.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsClient: in-memory cache client using cashews
        - FallbackCachePool: Redis→Cashews degradation proxy
    """

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

    async def hexists_many(self, name: str, keys: list[str]) -> list[bool]:
        """Check if multiple hash fields exist.

        Args:
            name: Hash name.
            keys: List of field keys.

        Returns:
            List of booleans indicating existence for each key.
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

    async def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        """Increment a hash field by amount.

        Args:
            name: Hash name.
            key: Field key.
            amount: Amount to increment by (default 1).

        Returns:
            New value after increment.
        """
        ...


@runtime_checkable
class CacheList(Protocol):
    """Protocol for list cache operations.

    Defines list data structure operations supported by cache backends.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsClient: in-memory cache client using cashews
        - FallbackCachePool: Redis→Cashews degradation proxy
    """

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

    async def lrange(self, name: str, start: int, stop: int) -> list[str]:
        """Return a slice of a list.

        Args:
            name: List name.
            start: Start index (0-based, inclusive).
            stop: Stop index (exclusive; -1 means to end).

        Returns:
            List of elements in the specified range.
        """
        ...

    async def ltrim(self, name: str, start: int, stop: int) -> None:
        """Trim a list to the specified range, removing elements outside it.

        Args:
            name: List name.
            start: Start index to keep (0-based, inclusive).
            stop: Stop index to keep (inclusive; -1 means to end).
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


@runtime_checkable
class CacheSortedSet(Protocol):
    """Protocol for sorted set cache operations.

    Defines sorted set data structure operations supported by cache backends.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsClient: in-memory cache client using cashews
        - FallbackCachePool: Redis→Cashews degradation proxy
    """

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


@runtime_checkable
class CachePipeline(Protocol):
    """Protocol for pipeline cache operations.

    Defines pipeline/batch operation support for cache backends.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsClient: in-memory cache client using cashews
        - FallbackCachePool: Redis→Cashews degradation proxy
    """

    def pipeline(self) -> Any:
        """Return a pipeline for batch operations.

        Returns:
            A pipeline object supporting hincrby, hset, expire, etc.
            Must be used as an async context manager:
                async with pool.pipeline() as pipe:
                    pipe.hincrby(...)
                    await pipe.execute()
        """
        ...


@runtime_checkable
class CacheScan(Protocol):
    """Protocol for scan cache operations.

    Defines incremental key scanning operations for cache backends.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsClient: in-memory cache client using cashews
        - FallbackCachePool: Redis→Cashews degradation proxy
    """

    async def scan_iter(self, pattern: str, count: int = 100):
        """Iterate over keys matching pattern using SCAN (non-blocking).

        Args:
            pattern: Pattern to match (e.g., "session:*").
            count: Hint for number of keys per iteration.

        Yields:
            Keys matching the pattern.
        """
        ...


@runtime_checkable
class CachePool(
    CacheKV,
    CacheHash,
    CacheList,
    CacheSortedSet,
    CachePipeline,
    CacheScan,
    Protocol,
):
    """Protocol for cache implementations (Redis, Cashews, etc.).

    Defines a unified interface for cache operations that can be
    implemented by different cache backends. Combines all cache
    sub-protocols (CacheKV, CacheHash, CacheList, CacheSortedSet,
    CachePipeline, CacheScan) and adds lifecycle management.

    Implementations:
        - RedisClient: redis-py async wrapper
        - CashewsClient: in-memory cache client using cashews
        - FallbackCachePool: Redis→Cashews degradation proxy
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
