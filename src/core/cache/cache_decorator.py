# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Cache decorator for API responses."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import json_repair

from core.cache.redis import RedisClient
from core.observability.logging import get_logger

log = get_logger("cache_decorator")

T = TypeVar("T")


def get_redis_client() -> RedisClient | None:
    """Get the Redis client from the container.

    Returns:
        RedisClient instance or None if not initialized.
    """
    try:
        from container import get_container

        container = get_container()
        return container.redis_client()
    except Exception:
        return None


def cache_result(
    ttl: int = 3600,
    key_prefix: str = "",
    key_builder: Callable[..., str] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to cache function results in Redis.

    Args:
        ttl: Time to live in seconds.
        key_prefix: Prefix for cache keys.
        key_builder: Optional function to build cache key from arguments.

    Returns:
        Decorated function.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            redis = get_redis_client()
            if redis is None:
                return await func(*args, **kwargs)

            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                key_parts = [str(arg) for arg in args if not isinstance(arg, object)]
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = f"{key_prefix}:{func.__name__}:{hash('|'.join(key_parts))}"

            try:
                cached = await redis.get(cache_key)
                if cached:
                    log.debug("cache_hit", key=cache_key)
                    return json_repair.loads(cached)
            except Exception as e:
                log.warning("cache_read_failed", key=cache_key, error=str(e))

            result = await func(*args, **kwargs)

            try:
                await redis.set(cache_key, json.dumps(result), ex=ttl)
                log.debug("cache_set", key=cache_key, ttl=ttl)
            except Exception as e:
                log.warning("cache_write_failed", key=cache_key, error=str(e))

            return result

        return wrapper

    return decorator


async def invalidate_cache(key_pattern: str) -> int:
    """Invalidate cache entries matching a pattern using SCAN.

    Uses SCAN instead of KEYS for better performance on large datasets.
    This is an async function that must be awaited.

    Args:
        key_pattern: Pattern to match cache keys.

    Returns:
        Number of keys deleted.
    """
    redis = get_redis_client()
    if redis is None:
        return 0

    deleted_count = 0
    try:
        # Use SCAN instead of KEYS for better performance
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=f"{key_pattern}*", count=100)
            if keys:
                await redis.delete(*keys)
                deleted_count += len(keys)
            if cursor == 0:
                break

        if deleted_count > 0:
            log.info("cache_invalidated", pattern=key_pattern, count=deleted_count)
        return deleted_count
    except Exception as e:
        log.warning("cache_invalidation_failed", pattern=key_pattern, error=str(e))
        return 0
