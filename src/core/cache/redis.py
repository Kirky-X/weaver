# Copyright (c) 2026 KirkyX. All Rights Reserved
"""redis-py async wrapper."""

from __future__ import annotations

import time
from typing import Any, cast

from redis.asyncio import ConnectionPool, Redis

from core.observability.logging import get_logger
from core.utils.sanitize import sanitize_dsn

log = get_logger(__name__)


class RedisClient:
    """Thin async wrapper around redis-py with connection pooling.

    Implements:
        - CachePool: Async cache operations with Redis backend
    """

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
            log.info("redis_client_started", url=sanitize_dsn(self._url))
        except Exception as exc:
            await self._redis.close()
            self._redis = None
            self._pool = None
            log.error("redis_connection_failed", error=str(exc))
            raise ConnectionError(f"Failed to connect to Redis: {exc}") from exc

    async def shutdown(self) -> None:
        """Close the Redis connection pool."""
        if self._redis:
            await self._redis.aclose()
            log.info("redis_client_closed")

    async def ping(self) -> bool:
        """Ping Redis server to check connectivity.

        Returns:
            True if ping successful.

        Raises:
            RuntimeError: If client not started.
            ConnectionError: If ping fails.
        """
        return await self.client.ping()

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

    async def mget(self, keys: list[str]) -> list[str | None]:
        """Get multiple values by keys.

        Args:
            keys: List of keys to retrieve.

        Returns:
            List of values (None for missing keys).
        """
        if not keys:
            return []
        return await self.client.mget(keys)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
    ) -> None:
        """Set a key-value pair with optional expiration."""
        await self.client.set(key, value, ex=ex)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """Set a key with expiration.

        Args:
            key: Key to set.
            ttl: Time to live in seconds.
            value: Value to store.
        """
        await self.client.setex(key, ttl, value)

    async def hget(self, name: str, key: str) -> str | None:
        """Get a hash field value."""
        return await self.client.hget(name, key)

    async def hset(self, name: str, key: str, value: str) -> None:
        """Set a hash field value."""
        await self.client.hset(name, key, value)

    async def hexists(self, name: str, key: str) -> bool:
        """Check if a hash field exists."""
        return await self.client.hexists(name, key)

    async def hgetall(self, name: str) -> dict[str, str]:
        """Get all fields and values in a hash."""
        return await self.client.hgetall(name)

    async def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        """Increment a hash field by amount.

        Args:
            name: Hash name.
            key: Field key.
            amount: Amount to increment (default 1).

        Returns:
            New value after increment.
        """
        return await self.client.hincrby(name, key, amount)

    async def hdel(self, name: str, *keys: str) -> int:
        """Delete hash fields."""
        return await self.client.hdel(name, *keys)

    async def hexists_many(self, name: str, keys: list[str]) -> list[bool]:
        """Check if multiple hash fields exist using pipeline."""
        pipe = self.client.pipeline()
        for key in keys:
            pipe.hexists(name, key)
        results = await pipe.execute()
        return list(results)

    async def lpush(self, name: str, *values: str) -> int:
        """Prepend values to a list."""
        return await self.client.lpush(name, *values)

    async def llen(self, name: str) -> int:
        """Return the length of a list."""
        return await self.client.llen(name)

    async def rpop(self, name: str) -> str | None:
        """Remove and return the last element of a list."""
        return await self.client.rpop(name)

    async def lrange(self, name: str, start: int, stop: int) -> list[str]:
        """Return a slice of a list."""
        return await self.client.lrange(name, start, stop)

    async def ltrim(self, name: str, start: int, stop: int) -> None:
        """Trim a list to the specified range."""
        await self.client.ltrim(name, start, stop)

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

    async def scan_iter(self, pattern: str, count: int = 100):
        """Iterate over keys matching pattern using SCAN (non-blocking).

        Args:
            pattern: Pattern to match (e.g., "session:*").
            count: Hint for number of keys per iteration.

        Yields:
            Keys matching the pattern.
        """
        cursor = 0
        while True:
            cursor, keys = await self.client.scan(cursor, match=pattern, count=count)
            for key in keys:
                yield key
            if cursor == 0:
                break

    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int = 10,
    ) -> tuple[int, list[str]]:
        """Scan keys matching a pattern incrementally.

        Args:
            cursor: Cursor position (0 to start).
            match: Pattern to match.
            count: Hint for number of keys per iteration.

        Returns:
            Tuple of (new_cursor, list of keys).
        """
        return await self.client.scan(cursor=cursor, match=match, count=count)

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys.

        Args:
            keys: Keys to delete.

        Returns:
            Number of keys deleted.
        """
        if not keys:
            return 0
        return await self.client.delete(*keys)

    async def expire(self, name: str, seconds: int) -> bool:
        """Set expiration time for a key.

        Args:
            name: Key to set expiration on.
            seconds: Time to live in seconds.

        Returns:
            True if timeout was set, False if key doesn't exist.
        """
        return await self.client.expire(name, seconds)

    def pipeline(self) -> Any:
        """Return a pipeline for batch operations."""
        return self.client.pipeline()

    async def register_script(self, script: str) -> Any:
        """Register a Lua script."""
        return self.client.register_script(script)


# ── Cashews-based Redis fallback ──────────────────────────────


class _CashewsPipeline:
    """Pseudo-pipeline that buffers commands and replays them."""

    def __init__(self, fallback: CashewsClient) -> None:
        self._fallback = fallback
        self._commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def execute_command(self, *args: Any, **kwargs: Any) -> None:
        self._commands.append(("execute_command", args, kwargs))

    # ── Buffered convenience methods ──────────────────────────

    def get(self, key: str) -> None:
        self._commands.append(("get", (key,), {}))

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._commands.append(("set", (key, value), {"ex": ex}))

    def delete(self, *keys: str) -> None:
        self._commands.append(("delete", keys, {}))

    def hset(self, name: str, key: str, value: str) -> None:
        self._commands.append(("hset", (name, key, value), {}))

    def hget(self, name: str, key: str) -> None:
        self._commands.append(("hget", (name, key), {}))

    def hdel(self, name: str, *keys: str) -> None:
        self._commands.append(("hdel", (name, *keys), {}))

    def lpush(self, name: str, *values: str) -> None:
        self._commands.append(("lpush", (name, *values), {}))

    def zadd(self, name: str, mapping: dict[str, float]) -> None:
        self._commands.append(("zadd", (name, mapping), {}))

    def expire(self, name: str, seconds: int) -> None:
        self._commands.append(("expire", (name, seconds), {}))

    async def execute(self) -> list[Any]:
        """Replay all buffered commands sequentially."""
        results: list[Any] = []
        for method_name, args, kwargs in self._commands:
            method = getattr(self._fallback, method_name, None)
            if method and callable(method):
                result = method(*args, **kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                results.append(result)
            else:
                results.append(None)
        return results

    async def __aenter__(self) -> _CashewsPipeline:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class _CashewsScript:
    """Placeholder for Lua script execution — not supported by cashews.

    The cashews library does not support Lua script evaluation via EVAL/EVALSHA.
    This class provides interface compatibility but will raise NotImplementedError
    if actually called. Use a real Redis connection for Lua script functionality.
    """

    def __init__(self, _script: str) -> None:
        """Store the script (unused, as cashews cannot execute Lua scripts).

        Args:
            _script: Lua script content (ignored).
        """
        self._script = _script

    async def __call__(self, *keys: str, args: list[str] | None = None) -> Any:
        """Raise NotImplementedError as Lua scripts cannot be executed.

        Raises:
            NotImplementedError: Always raised because cashews does not support Lua eval.
        """
        raise NotImplementedError(
            "Lua script execution is not supported by cashews. "
            "Use a real Redis connection for this functionality."
        )


class CashewsClient:
    """In-memory cache client built on cashews.

    Uses cashews ``mem://`` backend for the underlying cache store and
    supplements it with in-memory dicts/lists for Redis-specific data
    structures (hashes, sorted sets, lists).

    Suitable for testing and standalone operation without a real Redis server.

    Implements:
        - CachePool: Async cache operations with in-memory backend
    """

    def __init__(self) -> None:
        import cashews

        self._cache = cashews.cache
        self._cache.setup("mem://")
        self._store: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._lists: dict[str, list[str]] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}

    # ── Lifecycle ──────────────────────────────────────────────

    async def startup(self) -> None:
        """No-op: cashews mem:// backend requires no initialization."""
        log.info("cashews_redis_fallback_started")

    async def shutdown(self) -> None:
        """No-op: in-memory store requires no cleanup."""
        log.info("cashews_redis_fallback_closed")

    async def ping(self) -> bool:
        return True

    @property
    def client(self) -> CashewsClient:
        return self

    # ── Key / Value ────────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        self._check_expiry(key)
        return self._store.get(key)

    async def mget(self, keys: list[str]) -> list[str | None]:
        """Get multiple values by keys."""
        return [await self.get(key) for key in keys]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._expiry[key] = time.monotonic() + ex

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """Set a key with expiration."""
        await self.set(key, value, ex=ttl)

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                self._expiry.pop(key, None)
                count += 1
        return count

    async def expire(self, name: str, seconds: int) -> bool:
        """Set TTL for any data structure (key, hash, list, sorted set)."""
        # Check all data structures
        exists = (
            name in self._store
            or name in self._hashes
            or name in self._lists
            or name in self._sorted_sets
        )
        if exists:
            self._expiry[name] = time.monotonic() + seconds
            return True
        return False

    # ── Hash ───────────────────────────────────────────────────

    async def hget(self, name: str, key: str) -> str | None:
        self._check_expiry(name)
        return self._hashes.get(name, {}).get(key)

    async def hset(self, name: str, key: str, value: str) -> None:
        self._hashes.setdefault(name, {})[key] = value

    async def hexists(self, name: str, key: str) -> bool:
        self._check_expiry(name)
        return key in self._hashes.get(name, {})

    async def hexists_many(self, name: str, keys: list[str]) -> list[bool]:
        self._check_expiry(name)
        h = self._hashes.get(name, {})
        return [key in h for key in keys]

    async def hgetall(self, name: str) -> dict[str, str]:
        self._check_expiry(name)
        return dict(self._hashes.get(name, {}))

    async def hdel(self, name: str, *keys: str) -> int:
        h = self._hashes.get(name, {})
        count = sum(1 for k in keys if h.pop(k, None) is not None)
        return count

    async def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        h = self._hashes.setdefault(name, {})
        current = int(h.get(key, "0"))
        new_val = current + amount
        h[key] = str(new_val)
        return new_val

    # ── List ───────────────────────────────────────────────────

    async def lpush(self, name: str, *values: str) -> int:
        lst = self._lists.setdefault(name, [])
        lst[:0] = list(values)
        return len(lst)

    async def llen(self, name: str) -> int:
        return len(self._lists.get(name, []))

    async def rpop(self, name: str) -> str | None:
        lst = self._lists.get(name, [])
        if lst:
            return lst.pop()
        return None

    async def lrange(self, name: str, start: int, stop: int) -> list[str]:
        """Return a slice of a list."""
        self._check_expiry(name)
        lst = self._lists.get(name, [])
        if stop == -1:
            return list(lst[start:])
        return list(lst[start : stop + 1])

    async def ltrim(self, name: str, start: int, stop: int) -> None:
        """Trim a list to the specified range."""
        self._check_expiry(name)
        lst = self._lists.get(name, [])
        if stop == -1:
            trimmed = lst[start:]
        else:
            trimmed = lst[start : stop + 1]
        self._lists[name] = trimmed

    # ── Sorted Set ─────────────────────────────────────────────

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        ss = self._sorted_sets.setdefault(name, {})
        added = 0
        for member, score in mapping.items():
            if member not in ss:
                added += 1
            ss[member] = score
        return added

    async def zrangebyscore(
        self,
        name: str,
        min_score: float,
        max_score: float,
        start: int = 0,
        num: int = 100,
    ) -> list[str]:
        ss = self._sorted_sets.get(name, {})
        filtered = sorted(
            (m for m, s in ss.items() if min_score <= s <= max_score),
            key=lambda m: ss[m],
        )
        return filtered[start : start + num]

    async def zrem(self, name: str, *members: str) -> int:
        ss = self._sorted_sets.get(name, {})
        return sum(1 for m in members if ss.pop(m, None) is not None)

    # ── Scan ───────────────────────────────────────────────────

    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int = 10,
    ) -> tuple[int, list[str]]:
        all_keys = list(self._store.keys())
        if match:
            all_keys = [k for k in all_keys if self._match_pattern(k, match)]
        start = cursor
        end = start + count
        batch = all_keys[start:end]
        new_cursor = end if end < len(all_keys) else 0
        return new_cursor, batch

    async def scan_iter(self, pattern: str, count: int = 100):
        """Iterate over keys matching pattern."""
        cursor = 0
        while True:
            cursor, keys = await self.scan(cursor, match=pattern, count=count)
            for key in keys:
                yield key
            if cursor == 0:
                break

    # ── Pipeline / Script ──────────────────────────────────────

    def pipeline(self) -> _CashewsPipeline:
        """Return a pseudo-pipeline for batch operations."""
        return _CashewsPipeline(self)

    def register_script(self, script: str) -> _CashewsScript:
        """Return a placeholder script object (cashews has no Lua support).

        The returned object implements the script interface but will raise
        NotImplementedError when called. This maintains API compatibility
        while clearly indicating the limitation.

        Args:
            script: Lua script content.

        Returns:
            A placeholder _CashewsScript object that will raise NotImplementedError on execution.
        """
        return _CashewsScript(script)

    # ── Internal helpers ───────────────────────────────────────

    def _check_expiry(self, key: str) -> None:
        """Remove key if TTL has expired."""
        exp = self._expiry.get(key)
        if exp is not None and time.monotonic() > exp:
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            self._hashes.pop(key, None)
            self._lists.pop(key, None)
            self._sorted_sets.pop(key, None)

    @staticmethod
    def _match_pattern(key: str, pattern: str) -> bool:
        """Simple glob-style pattern matching (* and ?)."""
        import fnmatch

        return fnmatch.fnmatch(key, pattern)
