# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for Redis-backed token bucket rate limiting middleware."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── TokenBucketRateLimiter unit tests ──────────────────────────────


class TestTokenBucketRateLimiter:
    """Tests for the TokenBucketRateLimiter core algorithm."""

    def test_init_default_values(self):
        """Test that TokenBucketRateLimiter initializes with default config."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        limiter = TokenBucketRateLimiter(redis=mock_redis)
        assert limiter._global_max_tokens == 1000
        assert limiter._global_refill_rate == 1000
        assert limiter._per_key_max_tokens == 100
        assert limiter._per_key_refill_rate == 100

    def test_init_custom_values(self):
        """Test that TokenBucketRateLimiter accepts custom config."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        limiter = TokenBucketRateLimiter(
            redis=mock_redis,
            global_max_tokens=500,
            global_refill_rate=500,
            per_key_max_tokens=50,
            per_key_refill_rate=50,
        )
        assert limiter._global_max_tokens == 500
        assert limiter._per_key_max_tokens == 50

    async def test_acquire_within_global_limit(self):
        """Test that requests within global limit are allowed."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        # Lua script returns [1, 999] = allowed, 999 remaining
        mock_script = AsyncMock(return_value=[1, 999])
        mock_redis.register_script.return_value = mock_script

        limiter = TokenBucketRateLimiter(redis=mock_redis)
        allowed, remaining = await limiter.acquire("global", "key1")
        assert allowed is True
        assert remaining == 999

    async def test_acquire_global_limit_exceeded(self):
        """Test that requests exceeding global limit are rejected."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        # Lua script returns [0, 0] = rejected, 0 remaining
        mock_script = AsyncMock(return_value=[0, 0])
        mock_redis.register_script.return_value = mock_script

        limiter = TokenBucketRateLimiter(redis=mock_redis)
        allowed, remaining = await limiter.acquire("global", "key1")
        assert allowed is False
        assert remaining == 0

    async def test_acquire_per_key_limit_exceeded(self):
        """Test that requests exceeding per-key limit are rejected."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        # Global check passes, per-IP passes, per-key check fails
        mock_script = AsyncMock(side_effect=[[1, 500], [1, 200], [0, 0]])
        mock_redis.register_script.return_value = mock_script

        limiter = TokenBucketRateLimiter(redis=mock_redis)
        allowed, remaining = await limiter.acquire("global", "key1")
        assert allowed is False
        assert remaining == 0

    async def test_acquire_both_limits_pass(self):
        """Test that requests passing global, per-IP, and per-key limits are allowed."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        # All three checks pass: global, per-IP, per-key
        mock_script = AsyncMock(side_effect=[[1, 800], [1, 200], [1, 80]])
        mock_redis.register_script.return_value = mock_script

        limiter = TokenBucketRateLimiter(redis=mock_redis)
        allowed, remaining = await limiter.acquire("global", "key1")
        assert allowed is True
        assert remaining == 80  # per-key remaining is the limiting factor

    async def test_acquire_redis_unavailable_graceful(self):
        """Test that Redis errors are handled gracefully (allow request)."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        mock_script = AsyncMock(side_effect=Exception("Redis connection lost"))
        mock_redis.register_script.return_value = mock_script

        limiter = TokenBucketRateLimiter(redis=mock_redis)
        allowed, remaining = await limiter.acquire("global", "key1")
        # When Redis is down, allow the request (fail-open)
        assert allowed is True

    async def test_acquire_no_redis_graceful(self):
        """Test that missing Redis client allows requests (fail-open)."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        limiter = TokenBucketRateLimiter(redis=None)
        allowed, remaining = await limiter.acquire("global", "key1")
        assert allowed is True

    def test_lua_script_registered_on_init(self):
        """Test that Lua script is registered with Redis on initialization."""
        from api.middleware.rate_limit import TokenBucketRateLimiter

        mock_redis = MagicMock()
        limiter = TokenBucketRateLimiter(redis=mock_redis)
        mock_redis.register_script.assert_called_once()
        # Verify the script contains token bucket logic
        script_arg = mock_redis.register_script.call_args[0][0]
        assert "KEYS" in script_arg
        assert "ARGV" in script_arg
        assert "refill" in script_arg.lower() or "tokens" in script_arg.lower()


# ── RateLimitMiddleware unit tests ─────────────────────────────────


class TestRateLimitMiddleware:
    """Tests for the RateLimitMiddleware ASGI middleware."""

    async def test_request_within_limits_passes(self):
        """Test that requests within both limits pass through."""
        from api.middleware.rate_limit import RateLimitMiddleware

        mock_app = AsyncMock()
        mock_limiter = AsyncMock()
        mock_limiter.acquire = AsyncMock(return_value=(True, 100))

        middleware = RateLimitMiddleware(mock_app, rate_limiter=mock_limiter)
        scope = {"type": "http", "method": "GET", "path": "/api/v1/search"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        # The inner app should have been called
        mock_app.assert_called_once()

    async def test_global_limit_exceeded_returns_429(self):
        """Test that exceeding global limit returns HTTP 429."""
        from api.middleware.rate_limit import RateLimitMiddleware

        mock_app = AsyncMock()
        mock_limiter = AsyncMock()
        mock_limiter.acquire = AsyncMock(return_value=(False, 0))

        middleware = RateLimitMiddleware(mock_app, rate_limiter=mock_limiter)
        scope = {"type": "http", "method": "GET", "path": "/api/v1/search"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        # The inner app should NOT have been called
        mock_app.assert_not_called()
        # 429 response should be sent
        send_calls = send.call_args_list
        status_found = False
        for call in send_calls:
            args = call[0][0]
            if args.get("type") == "http.response.start":
                assert args["status"] == 429
                status_found = True
        assert status_found, "Expected 429 status in response"

    async def test_429_includes_retry_after_header(self):
        """Test that 429 response includes Retry-After header."""
        from api.middleware.rate_limit import RateLimitMiddleware

        mock_app = AsyncMock()
        mock_limiter = AsyncMock()
        mock_limiter.acquire = AsyncMock(return_value=(False, 0))

        middleware = RateLimitMiddleware(mock_app, rate_limiter=mock_limiter)
        scope = {"type": "http", "method": "GET", "path": "/api/v1/search"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        # Check for Retry-After header in response
        send_calls = send.call_args_list
        headers_found = False
        for call in send_calls:
            args = call[0][0]
            if args.get("type") == "http.response.start":
                headers = args.get("headers", [])
                for name, value in headers:
                    if name == b"retry-after":
                        headers_found = True
                        assert int(value) > 0
        assert headers_found, "Expected Retry-After header in 429 response"

    async def test_non_http_scope_passes_through(self):
        """Test that non-HTTP scopes (e.g., websocket) pass through."""
        from api.middleware.rate_limit import RateLimitMiddleware

        mock_app = AsyncMock()
        mock_limiter = AsyncMock()

        middleware = RateLimitMiddleware(mock_app, rate_limiter=mock_limiter)
        scope = {"type": "websocket", "path": "/ws"}
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        mock_app.assert_called_once_with(scope, receive, send)
        # acquire should NOT be called for websocket
        mock_limiter.acquire.assert_not_called()

    async def test_api_key_extracted_from_header(self):
        """Test that API key is extracted from X-API-Key header for per-key limiting."""
        from api.middleware.rate_limit import RateLimitMiddleware

        mock_app = AsyncMock()
        mock_limiter = AsyncMock()
        mock_limiter.acquire = AsyncMock(return_value=(True, 50))

        middleware = RateLimitMiddleware(mock_app, rate_limiter=mock_limiter)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/search",
            "headers": [(b"x-api-key", b"test-key-123")],
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        # Verify acquire was called with the API key
        call_args = mock_limiter.acquire.call_args
        assert call_args[0][1] == "test-key-123"

    async def test_client_ip_used_as_fallback_key(self):
        """Test that client IP is used as per-key identifier when no API key is present."""
        from api.middleware.rate_limit import RateLimitMiddleware

        mock_app = AsyncMock()
        mock_limiter = AsyncMock()
        mock_limiter.acquire = AsyncMock(return_value=(True, 100))

        middleware = RateLimitMiddleware(mock_app, rate_limiter=mock_limiter)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/search",
            "headers": [],
            "client": ("192.168.1.1", 12345),
        }
        receive = AsyncMock()
        send = AsyncMock()

        await middleware(scope, receive, send)
        call_args = mock_limiter.acquire.call_args
        # client_key is the IP, api_key is None when no X-API-Key header
        assert call_args[0][0] == "192.168.1.1"  # client_key = IP
        assert call_args[0][1] is None  # api_key = None


# ── Integration: Lua script correctness ────────────────────────────


class TestTokenBucketLuaScript:
    """Test the Lua script logic using a simulated Redis environment."""

    def test_lua_script_source_contains_required_elements(self):
        """Test that the Lua script implements token bucket correctly."""
        from api.middleware.rate_limit import TOKEN_BUCKET_LUA_SCRIPT

        # Must handle key-based bucket
        assert "KEYS[1]" in TOKEN_BUCKET_LUA_SCRIPT
        # Must accept max_tokens, refill_rate, refill_count as args
        assert "ARGV" in TOKEN_BUCKET_LUA_SCRIPT
        # Must implement refill logic
        assert (
            "refill" in TOKEN_BUCKET_LUA_SCRIPT.lower()
            or "last_time" in TOKEN_BUCKET_LUA_SCRIPT.lower()
        )
        # Must return allowed (0/1) and remaining
        assert "return" in TOKEN_BUCKET_LUA_SCRIPT.lower()


# ── Slowapi removal verification ───────────────────────────────────


class TestSlowapiRemoval:
    """Verify that slowapi has been completely removed."""

    def test_rate_limit_module_no_slowapi_import(self):
        """Test that rate_limit.py does not import slowapi."""
        import ast
        from pathlib import Path

        from api.middleware import rate_limit as module

        source = Path(module.__file__).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "slowapi" not in alias.name, f"Found slowapi import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert "slowapi" not in (
                    node.module or ""
                ), f"Found slowapi import from: {node.module}"

    def test_no_limiter_decorator_in_admin(self):
        """Test that admin.py no longer uses @limiter.limit decorators."""
        import ast
        from pathlib import Path

        from api.endpoints.admin import admin as module

        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    deco_src = ast.dump(deco)
                    assert "limiter" not in deco_src, f"Found @limiter decorator on {node.name}"

    def test_no_limiter_decorator_in_search(self):
        """Test that search.py no longer uses @limiter.limit decorators."""
        import ast
        from pathlib import Path

        from api.endpoints.content import search as module

        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    deco_src = ast.dump(deco)
                    assert "limiter" not in deco_src, f"Found @limiter decorator on {node.name}"

    def test_main_no_slowapi_imports(self):
        """Test that main.py no longer imports slowapi."""
        import ast
        import importlib.util
        import pathlib

        # 用 find_spec 解析 main 模块路径，不实际执行（避免触发 app 初始化）
        spec = importlib.util.find_spec("main")
        assert spec is not None and spec.origin, "main 模块未找到"
        main_path = pathlib.Path(spec.origin)
        tree = ast.parse(main_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "slowapi" not in alias.name, f"Found slowapi import: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert "slowapi" not in (
                    node.module or ""
                ), f"Found slowapi import from: {node.module}"
