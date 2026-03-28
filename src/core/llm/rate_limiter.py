# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Redis Token Bucket rate limiter (multi-process safe via Lua script).

适用场景:
- 生产环境代码 (container.py, queue_manager.py)
- 需要与 Redis 集成的场景
- 高性能、低延迟需求

对于独立脚本和开发测试，可使用 rate_limiter_pro.py 中的 RateLimiter。
"""

from __future__ import annotations

import time

# Lua script for atomic token consumption
_LUA_CONSUME = """
local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])   -- tokens per second refill rate
local now      = tonumber(ARGV[3])   -- current timestamp (float seconds)
local cost     = tonumber(ARGV[4])   -- tokens to consume (usually 1)

local info     = redis.call('HMGET', key, 'tokens', 'last_time')
local tokens   = tonumber(info[1]) or capacity
local last     = tonumber(info[2]) or now

-- Refill tokens based on elapsed time
tokens = math.min(capacity, tokens + (now - last) * rate)

if tokens < cost then
    -- Insufficient tokens; return wait time in seconds
    local wait = (cost - tokens) / rate
    return {0, tostring(wait)}
end

tokens = tokens - cost
redis.call('HMSET', key, 'tokens', tostring(tokens), 'last_time', tostring(now))
redis.call('EXPIRE', key, 3600)
return {1, "0"}
"""


class RedisTokenBucket:
    """Multi-process safe rate limiter using Redis + Lua atomic scripting.

    Each provider has its own token bucket keyed by name.
    The bucket refills at `rpm_limit / 60` tokens per second.
    """

    def __init__(self, redis_client: Any) -> None:
        # Support both RedisClient wrapper and raw Redis client
        if hasattr(redis_client, "client"):
            # RedisClient wrapper - get the underlying Redis client
            self._redis = redis_client.client
        else:
            self._redis = redis_client
        self._script = self._redis.register_script(_LUA_CONSUME)

    async def consume(self, provider: str, rpm_limit: int) -> float:
        """Attempt to consume one token.

        Args:
            provider: Provider name (used as bucket key).
            rpm_limit: Requests per minute limit for the provider.
                       If <= 0, returns 0.0 immediately (no rate limiting).

        Returns:
            0.0 if a token was consumed immediately.
            >0.0 indicates the number of seconds to wait.
        """
        if rpm_limit <= 0:
            return 0.0

        key = f"llm:rpm:{provider}"
        capacity = rpm_limit
        rate = rpm_limit / 60.0
        now = time.time()

        result = await self._script(keys=[key], args=[str(capacity), str(rate), str(now), "1"])
        allowed = int(result[0])
        wait = float(result[1])
        return 0.0 if allowed else wait
