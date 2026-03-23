# Copyright (c) 2026 KirkyX. All Rights Reserved
"""redis-py async wrapper."""

from __future__ import annotations

from typing import Any, cast

from redis.asyncio import ConnectionPool, Redis

from core.observability.logging import get_logger

log = get_logger("redis")


class RedisClient:
    """Thin async wrapper around redis-py with connection pooling."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._pool: ConnectionPool | None = None
        self._redis: Redis | None = None

    async def startup(self) -> None:
        """Initialize the Redis connection pool."""
        self._pool = ConnectionPool.from_url(
            self._url,
            decode_responses=True,
            max_connections=50,
        )
        self._redis = Redis(connection_pool=self._pool)
        try:
            await self._redis.ping()
            log.info("redis_client_started", url=self._url.split("@")[-1])
        except Exception as exc:
            await self._redis.close()
            self._redis = None
            self._pool = None
            log.error("redis_connection_failed", error=str(exc))
            raise ConnectionError(f"Failed to connect to Redis: {exc}") from exc

    async def shutdown(self) -> None:
        """Close the Redis connection pool."""
        if self._redis:
            await self._redis.close()
            log.info("redis_client_closed")

    @property
    def client(self) -> Redis:
        """Return the raw Redis client.

        Raises:
            RuntimeError: If client has not been started.
        """
        if self._redis is None:
            raise RuntimeError("RedisClient not started. Call startup() first.")
        return self._redis

    # ── Convenience methods ──────────────────────────────────

    async def get(self, key: str) -> str | None:
        """Get a value by key."""
        return await self.client.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
    ) -> None:
        """Set a key-value pair with optional expiration."""
        await self.client.set(key, value, ex=ex)

    async def hget(self, name: str, key: str) -> str | None:
        """Get a hash field value."""
        return await self.client.hget(name, key)

    async def hset(self, name: str, key: str, value: str) -> None:
        """Set a hash field value."""
        await self.client.hset(name, key, value)

    async def hexists(self, name: str, key: str) -> bool:
        """Check if a hash field exists."""
        return await self.client.hexists(name, key)

    async def lpush(self, name: str, *values: str) -> int:
        """Prepend values to a list."""
        return await self.client.lpush(name, *values)

    async def llen(self, name: str) -> int:
        """Return the length of a list."""
        return await self.client.llen(name)

    async def rpop(self, name: str) -> str | None:
        """Remove and return the last element of a list."""
        return await self.client.rpop(name)

    async def zadd(
        self,
        name: str,
        mapping: dict[str, float],
    ) -> int:
        """Add members to a sorted set."""
        return await self.client.zadd(name, cast(Any, mapping))

    async def zrangebyscore(
        self,
        name: str,
        min_score: float,
        max_score: float,
        start: int = 0,
        num: int = 100,
    ) -> list[str]:
        """Return members in a sorted set by score range."""
        return await self.client.zrangebyscore(
            name,
            min_score,
            max_score,
            start=start,
            num=num,
        )

    async def zrem(self, name: str, *members: str) -> int:
        """Remove members from a sorted set."""
        return await self.client.zrem(name, *members)

    async def keys(self, pattern: str) -> list[str]:
        """Find keys matching a pattern."""
        return await self.client.keys(pattern)

    def pipeline(self) -> Any:
        """Return a pipeline for batch operations."""
        return self.client.pipeline()

    async def register_script(self, script: str) -> Any:
        """Register a Lua script."""
        return self.client.register_script(script)
