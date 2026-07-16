# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Rate limiting middleware using Redis-backed token bucket.

Implements:
    - LocalTokenBucket: In-memory token bucket for fail-close fallback
    - TokenBucketRateLimiter: Core token bucket algorithm with Redis Lua scripts
    - RateLimitMiddleware: ASGI middleware for global + per-key rate limiting

Replaces the previous slowapi-based implementation with a Redis-backed
token bucket that provides:
    - Global limit: 1000 requests/second
    - Per-API-Key limit: 100 requests/second
    - HTTP 429 with Retry-After header when limits exceeded
    - Fail-close behavior when Redis is unavailable (local token bucket fallback)
    - X-RateLimit-Fallback header when using local fallback
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
_PER_IP_BUCKET_PREFIX = "ratelimit:ip"
_PER_KEY_BUCKET_PREFIX = "ratelimit:key"


class LocalTokenBucket:
    """In-memory token bucket for fail-close fallback when Redis is unavailable.

    Uses time.monotonic() for monotonic time tracking. Each key gets its
    own independent bucket state.

    Args:
        max_tokens: Maximum number of tokens in the bucket.
        refill_rate: Number of tokens refilled per second.

    """

    def __init__(self, max_tokens: int, refill_rate: int) -> None:
        self._max_tokens = max_tokens
        self._refill_rate = refill_rate
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_time)

    def acquire(self, key: str = "_default") -> bool:
        """Try to consume one token from the bucket for the given key.

        Args:
            key: Bucket key (e.g., client IP or API key).

        Returns:
            True if a token was available and consumed, False otherwise.

        """
        now = time.monotonic()

        if key in self._buckets:
            tokens, last_time = self._buckets[key]
            elapsed = now - last_time
            if elapsed > 0:
                tokens = min(self._max_tokens, tokens + elapsed * self._refill_rate)
            last_time = now
        else:
            tokens = float(self._max_tokens)
            last_time = now

        if tokens >= 1:
            tokens -= 1
            self._buckets[key] = (tokens, last_time)
            return True
        else:
            self._buckets[key] = (tokens, last_time)
            return False


class TokenBucketRateLimiter:
    """Redis-backed token bucket rate limiter with local fallback.

    Implements atomic token bucket algorithm using Redis Lua scripts
    for global, per-IP, and per-key rate limiting. When Redis is unavailable,
    falls back to a local in-memory token bucket (fail-close).

    Check order: global → per-IP → per-key.

    Args:
        redis: CachePool instance (RedisClient or compatible).
        global_max_tokens: Maximum tokens in the global bucket.
        global_refill_rate: Token refill rate per second for global bucket.
        per_ip_max_tokens: Maximum tokens per IP bucket (default 3000).
        per_ip_refill_rate: Token refill rate per second per IP (default 50).
        per_key_max_tokens: Maximum tokens per API key bucket.
        per_key_refill_rate: Token refill rate per second per key.

    """

    def __init__(
        self,
        redis: Any,
        global_max_tokens: int = 1000,
        global_refill_rate: int = 1000,
        per_ip_max_tokens: int = 3000,
        per_ip_refill_rate: int = 50,
        per_key_max_tokens: int = 100,
        per_key_refill_rate: int = 100,
    ) -> None:
        self._redis = redis
        self._global_max_tokens = global_max_tokens
        self._global_refill_rate = global_refill_rate
        self._per_ip_max_tokens = per_ip_max_tokens
        self._per_ip_refill_rate = per_ip_refill_rate
        self._per_key_max_tokens = per_key_max_tokens
        self._per_key_refill_rate = per_key_refill_rate
        self._fallback_active: bool = False

        # Local fallback buckets (used when Redis is unavailable)
        self._local_global_bucket = LocalTokenBucket(
            max_tokens=global_max_tokens,
            refill_rate=global_refill_rate,
        )
        self._local_per_ip_bucket = LocalTokenBucket(
            max_tokens=per_ip_max_tokens,
            refill_rate=per_ip_refill_rate,
        )
        self._local_per_key_bucket = LocalTokenBucket(
            max_tokens=per_key_max_tokens,
            refill_rate=per_key_refill_rate,
        )

        if redis is not None:
            # If redis is a FallbackCachePool with unhealthy primary, the
            # registered script will be a _CashewsScript that cannot execute
            # Lua. Pre-emptively activate local fallback to avoid TypeError
            # on every request (which would otherwise log CRITICAL).
            if hasattr(redis, "primary_healthy") and not redis.primary_healthy:
                self._script = None
                self._fallback_active = True
            else:
                self._script = redis.register_script(TOKEN_BUCKET_LUA_SCRIPT)
        else:
            self._script = None
            self._fallback_active = True

    @property
    def fallback_active(self) -> bool:
        """Whether the rate limiter is using local fallback mode."""
        return self._fallback_active

    async def acquire(
        self,
        client_key: str,
        api_key: str | None = None,
    ) -> tuple[bool, int]:
        """Check global, per-IP, and per-key rate limits.

        Check order: global → per-IP → per-key.

        Args:
            client_key: Client identifier (IP address or composite key).
            api_key: Optional API key for per-key limiting.

        Returns:
            Tuple of (allowed, remaining_tokens). remaining is the
            minimum of global, per-IP, and per-key remaining tokens.

        """
        if self._fallback_active:
            return self._acquire_local(client_key, api_key)

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

            # Check per-IP bucket
            per_ip_result = await self._script(
                keys=[f"{_PER_IP_BUCKET_PREFIX}:{client_key}"],
                args=[
                    self._per_ip_max_tokens,
                    self._per_ip_refill_rate,
                    1,  # consume 1 token
                    now,
                ],
            )
            per_ip_allowed, per_ip_remaining = per_ip_result[0], per_ip_result[1]

            if not per_ip_allowed:
                log.debug("rate_limit_per_ip_exceeded", client_ip=client_key)
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

            remaining = min(global_remaining, per_ip_remaining, per_key_remaining)
            return True, remaining

        except Exception as exc:
            log.critical(
                "rate_limit_redis_failure_fail_close",
                error=str(exc),
                exc_type=type(exc).__name__,
                client_ip=client_key,
            )
            # Fail-close: switch to local token bucket
            self._fallback_active = True
            return self._acquire_local(client_key, api_key)

    def _acquire_local(
        self,
        client_key: str,
        api_key: str | None = None,
    ) -> tuple[bool, int]:
        """Rate limit using local in-memory token bucket.

        Check order: global → per-IP → per-key.

        Args:
            client_key: Client identifier.
            api_key: Optional API key for per-key limiting.

        Returns:
            Tuple of (allowed, remaining_tokens).

        """
        global_allowed = self._local_global_bucket.acquire("_global")
        if not global_allowed:
            log.debug("rate_limit_local_global_exceeded", client=client_key)
            return False, 0

        per_ip_allowed = self._local_per_ip_bucket.acquire(client_key)
        if not per_ip_allowed:
            log.debug("rate_limit_local_per_ip_exceeded", client_ip=client_key)
            return False, 0

        per_key_id = api_key if api_key else client_key
        per_key_allowed = self._local_per_key_bucket.acquire(per_key_id)
        if not per_key_allowed:
            log.debug("rate_limit_local_per_key_exceeded", key=per_key_id)
            return False, 0

        return True, self._global_max_tokens


class RateLimitMiddleware:
    """ASGI middleware for Redis-backed token bucket rate limiting.

    Intercepts HTTP requests and enforces global + per-key rate limits.
    Returns HTTP 429 with Retry-After header when limits are exceeded.
    Adds X-RateLimit-Fallback header when using local fallback mode.

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

        # If using local fallback, add X-RateLimit-Fallback header
        if self._rate_limiter.fallback_active:
            await self._send_with_fallback_header(scope, receive, send)
        else:
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

    async def _send_with_fallback_header(self, scope: dict, receive: Any, send: Any) -> None:
        """Forward request to app, injecting X-RateLimit-Fallback header into response."""

        async def send_with_header(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"x-ratelimit-fallback", b"local"])
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, send_with_header)

    async def _send_429(self, send: Any, limit_type: str = "unknown") -> None:
        """Send HTTP 429 Too Many Requests response.

        Args:
            send: ASGI send callable.
            limit_type: Type of rate limit that was exceeded (global/ip/key).

        """
        retry_after = 1  # seconds until next token refill
        body = b'{"detail":"Rate limit exceeded"}'

        headers: list[tuple[bytes, bytes]] = [
            [b"content-type", b"application/json"],
            [b"retry-after", str(retry_after).encode()],
        ]

        if limit_type == "ip":
            headers.append([b"x-ratelimit-ip-limit", b"exceeded"])

        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
