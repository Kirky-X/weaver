# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for RedisTokenBucket rate limiter."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.rate_limiter import RedisTokenBucket


def _make_redis_mock(script_return=None):
    """Create a mock Redis client without a 'client' attribute.

    MagicMock() auto-creates attributes, so hasattr(..., "client") is True.
    Using spec=[] prevents that, ensuring RedisTokenBucket uses the raw mock.
    """
    mock = MagicMock(spec=["register_script"])
    if script_return is not None:
        mock.register_script = MagicMock(return_value=script_return)
    else:
        mock.register_script = MagicMock(return_value=MagicMock())
    return mock


class TestRedisTokenBucket:
    """Tests for RedisTokenBucket."""

    def test_initialization(self):
        """Test rate limiter initializes correctly."""
        mock_redis = _make_redis_mock()
        bucket = RedisTokenBucket(mock_redis)
        assert bucket._redis is mock_redis
        assert bucket._script is not None

    def test_script_registration(self):
        """Test Lua script is registered on initialization."""
        mock_script = MagicMock()
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        mock_redis.register_script.assert_called_once()

    @pytest.mark.asyncio
    async def test_consume_immediate(self):
        """Test consume returns 0 when tokens are available."""
        mock_script = AsyncMock(return_value=[1, "0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        result = await bucket.consume("openai", 60)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_consume_wait_time(self):
        """Test consume returns wait time when tokens exhausted."""
        mock_script = AsyncMock(return_value=[0, "2.5"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        result = await bucket.consume("openai", 60)
        assert result == 2.5

    @pytest.mark.asyncio
    async def test_consume_key_format(self):
        """Test consume uses correct key format."""
        mock_script = AsyncMock(return_value=[1, "0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        await bucket.consume("anthropic", 100)
        call_args = mock_script.call_args
        assert "llm:rpm:anthropic" in call_args[1]["keys"]

    @pytest.mark.asyncio
    async def test_consume_capacity_calculation(self):
        """Test capacity is set to rpm_limit."""
        mock_script = AsyncMock(return_value=[1, "0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        await bucket.consume("openai", 120)
        call_args = mock_script.call_args
        args = call_args[1]["args"]
        assert args[0] == "120"

    @pytest.mark.asyncio
    async def test_consume_rate_calculation(self):
        """Test rate is calculated as rpm_limit / 60."""
        mock_script = AsyncMock(return_value=[1, "0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        await bucket.consume("openai", 60)
        call_args = mock_script.call_args
        args = call_args[1]["args"]
        expected_rate = 60 / 60.0
        assert float(args[1]) == expected_rate

    @pytest.mark.asyncio
    async def test_consume_different_providers(self):
        """Test consume works with different providers."""
        mock_script = AsyncMock(return_value=[1, "0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        await bucket.consume("openai", 60)
        await bucket.consume("anthropic", 100)
        await bucket.consume("deepseek", 30)
        assert mock_script.call_count == 3

    @pytest.mark.asyncio
    async def test_consume_cost_is_one(self):
        """Test consume uses cost of 1 token."""
        mock_script = AsyncMock(return_value=[1, "0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        await bucket.consume("openai", 60)
        call_args = mock_script.call_args
        args = call_args[1]["args"]
        assert args[3] == "1"

    def test_lua_script_content(self):
        """Test Lua script contains expected logic."""
        from core.llm.rate_limiter import _LUA_CONSUME

        assert "HMGET" in _LUA_CONSUME
        assert "HMSET" in _LUA_CONSUME
        assert "EXPIRE" in _LUA_CONSUME
        assert "tokens" in _LUA_CONSUME
        assert "last_time" in _LUA_CONSUME

    @pytest.mark.asyncio
    async def test_consume_high_rpm(self):
        """Test consume with high RPM limit."""
        mock_script = AsyncMock(return_value=[1, "0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        result = await bucket.consume("openai", 10000)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_consume_low_rpm(self):
        """Test consume with low RPM limit."""
        mock_script = AsyncMock(return_value=[0, "10.0"])
        mock_redis = _make_redis_mock(script_return=mock_script)
        bucket = RedisTokenBucket(mock_redis)
        result = await bucket.consume("slow_provider", 6)
        assert result == 10.0
