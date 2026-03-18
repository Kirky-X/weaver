# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Core cache module - Redis client and cache utilities."""

from core.cache.cache_decorator import cache_result, get_redis_client, invalidate_cache
from core.cache.redis import RedisClient

__all__ = [
    "RedisClient",
    "cache_result",
    "get_redis_client",
    "invalidate_cache",
]
