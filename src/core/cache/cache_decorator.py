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


def invalidate_cache(key_pattern: str) -> None:
    """Invalidate cache entries matching a pattern.

    Args:
        key_pattern: Pattern to match cache keys.
    """
    redis = get_redis_client()
    if redis is None:
        return

    try:
        keys = redis.keys(f"{key_pattern}*")
        if keys:
            redis.delete(*keys)
            log.info("cache_invalidated", pattern=key_pattern, count=len(keys))
    except Exception as e:
        log.warning("cache_invalidation_failed", pattern=key_pattern, error=str(e))
