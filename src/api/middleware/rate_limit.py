# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Rate limiting middleware using Redis-backed token bucket.

Implements:
    - TokenBucketRateLimiter: Core token bucket algorithm with Redis Lua scripts
    - RateLimitMiddleware: ASGI middleware for global + per-key rate limiting

Replaces the previous slowapi-based implementation with a Redis-backed
token bucket that provides:
    - Global limit: 1000 requests/second
    - Per-API-Key limit: 100 requests/second
    - HTTP 429 with Retry-After header when limits exceeded
    - Fail-open behavior when Redis is unavailable
"""

from __future__ import annotations

import time
from typing import Any

from core.observability import get_logger

log = get_logger(__name__)

# ── Lua script for atomic token bucket ─────────────────────────────

TOKEN_BUCKET_LUA_SCRIPT = """
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local refill_count = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'last_time')
local tokens = tonumber(bucket[1])
local last_time = tonumber(bucket[2])

if tokens == nil then
    tokens = max_tokens
    last_time = now
end

local elapsed = now - last_time
if elapsed > 0 then
    local refilled = elapsed * refill_rate
    tokens = math.min(max_tokens, tokens + refilled)
    last_time = now
end

if tokens >= refill_count then
    tokens = tokens - refill_count
    redis.call('HMSET', key, 'tokens', tokens, 'last_time', last_time)
    redis.call('EXPIRE', key, math.ceil(max_tokens / refill_rate) * 2)
    return {1, math.floor(tokens)}
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_time', last_time)
    redis.call('EXPIRE', key, math.ceil(max_tokens / refill_rate) * 2)
    return {0, 0}
end
"""

# ── Redis key prefixes ─────────────────────────────────────────────

_GLOBAL_BUCKET_PREFIX = "ratelimit:global"
_PER_KEY_BUCKET_PREFIX = "ratelimit:key"


class TokenBucketRateLimiter:
    """Redis-backed token bucket rate limiter.

    Implements atomic token bucket algorithm using Redis Lua scripts
    for both global and per-key rate limiting.

    Args:
        redis: CachePool instance (RedisClient or compatible).
        global_max_tokens: Maximum tokens in the global bucket.
        global_refill_rate: Token refill rate per second for global bucket.
        per_key_max_tokens: Maximum tokens per API key bucket.
        per_key_refill_rate: Token refill rate per second per key.

    """

    def __init__(
        self,
        redis: Any,
        global_max_tokens: int = 1000,
        global_refill_rate: int = 1000,
        per_key_max_tokens: int = 100,
        per_key_refill_rate: int = 100,
    ) -> None:
        self._redis = redis
        self._global_max_tokens = global_max_tokens
        self._global_refill_rate = global_refill_rate
        self._per_key_max_tokens = per_key_max_tokens
        self._per_key_refill_rate = per_key_refill_rate

        if redis is not None:
            self._script = redis.register_script(TOKEN_BUCKET_LUA_SCRIPT)
        else:
            self._script = None

    async def acquire(
        self,
        client_key: str,
        api_key: str | None = None,
    ) -> tuple[bool, int]:
        """Check both global and per-key rate limits.

        Args:
            client_key: Client identifier (IP address or composite key).
            api_key: Optional API key for per-key limiting.

        Returns:
            Tuple of (allowed, remaining_tokens). remaining is the
            minimum of global and per-key remaining tokens.

        """
        if self._script is None:
            return True, self._global_max_tokens

        now = time.time()
        per_key_id = api_key if api_key else client_key

        try:
            # Check global bucket
            global_result = await self._script(
                keys=[_GLOBAL_BUCKET_PREFIX],
                args=[
                    self._global_max_tokens,
                    self._global_refill_rate,
                    1,  # consume 1 token
                    now,
                ],
            )
            global_allowed, global_remaining = global_result[0], global_result[1]

            if not global_allowed:
                log.debug("rate_limit_global_exceeded", client=client_key)
                return False, 0

            # Check per-key bucket
            per_key_result = await self._script(
                keys=[f"{_PER_KEY_BUCKET_PREFIX}:{per_key_id}"],
                args=[
                    self._per_key_max_tokens,
                    self._per_key_refill_rate,
                    1,  # consume 1 token
                    now,
                ],
            )
            per_key_allowed, per_key_remaining = per_key_result[0], per_key_result[1]

            if not per_key_allowed:
                log.debug("rate_limit_per_key_exceeded", key=per_key_id)
                return False, 0

            remaining = min(global_remaining, per_key_remaining)
            return True, remaining

        except Exception:
            log.warning("rate_limit_redis_error", exc_info=True)
            # Fail-open: allow request when Redis is unavailable
            return True, self._global_max_tokens


class RateLimitMiddleware:
    """ASGI middleware for Redis-backed token bucket rate limiting.

    Intercepts HTTP requests and enforces global + per-key rate limits.
    Returns HTTP 429 with Retry-After header when limits are exceeded.

    Args:
        app: The ASGI application to wrap.
        rate_limiter: TokenBucketRateLimiter instance.

    """

    def __init__(self, app: Any, rate_limiter: TokenBucketRateLimiter) -> None:
        self._app = app
        self._rate_limiter = rate_limiter

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        """ASGI entry point: check rate limits before forwarding request."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Extract client key from scope
        client_key = self._extract_client_key(scope)
        api_key = self._extract_api_key(scope)

        allowed, _remaining = await self._rate_limiter.acquire(client_key, api_key)

        if not allowed:
            await self._send_429(send)
            return

        await self._app(scope, receive, send)

    def _extract_client_key(self, scope: dict) -> str:
        """Extract client IP from ASGI scope."""
        client = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    def _extract_api_key(self, scope: dict) -> str | None:
        """Extract API key from request headers."""
        headers = scope.get("headers", [])
        for name, value in headers:
            if name == b"x-api-key":
                return value.decode("utf-8", errors="replace")
        return None

    async def _send_429(self, send: Any) -> None:
        """Send HTTP 429 Too Many Requests response."""
        retry_after = 1  # seconds until next token refill
        body = b'{"detail":"Rate limit exceeded"}'

        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"retry-after", str(retry_after).encode()],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
