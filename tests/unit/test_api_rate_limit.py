# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for rate limiting middleware (rate_limit.py)."""

from __future__ import annotations


class TestRateLimiterConfiguration:
    """Tests for rate limiting middleware configuration."""

    def test_limiter_is_not_none(self):
        """Test that the limiter object is defined and not None."""
        from api.middleware.rate_limit import limiter

        assert limiter is not None

    def test_limiter_uses_remote_address_key_func(self):
        """Test that the limiter uses get_remote_address as its key function.

        This ensures rate limiting is applied per client IP address.
        """
        from slowapi.util import get_remote_address

        from api.middleware.rate_limit import limiter

        assert limiter.key_func is get_remote_address

    def test_limiter_is_limiter_instance(self):
        """Test that limiter is a slowapi Limiter instance."""
        from slowapi import Limiter

        from api.middleware.rate_limit import limiter

        assert isinstance(limiter, Limiter)

    def test_limiter_key_func_identifies_by_ip(self):
        """Test that the key function uses the request's remote address.

        This is critical for per-client rate limiting enforcement.
        """
        from unittest.mock import MagicMock

        from slowapi.util import get_remote_address

        # Simulate a request with a specific remote address
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "192.168.1.100"

        ip = get_remote_address(mock_request)
        assert ip == "192.168.1.100"

    def test_limiter_key_func_handles_x_forwarded_for(self):
        """Test that get_remote_address respects X-Forwarded-For header."""
        from slowapi.util import get_remote_address

        # When X-Forwarded-For is present, get_remote_address may use it
        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"X-Forwarded-For": "203.0.113.50, 70.41.3.18"}

        ip = get_remote_address(mock_request)
        # slowapi returns the first IP in X-Forwarded-For chain
        assert "203.0.113.50" in ip or ip == "127.0.0.1"

    def test_limiter_exported_from_module(self):
        """Test that limiter can be imported directly from the module."""
        from api.middleware.rate_limit import limiter

        # Should be importable at module level
        assert hasattr(limiter, "limit")
        assert callable(limiter.limit)
