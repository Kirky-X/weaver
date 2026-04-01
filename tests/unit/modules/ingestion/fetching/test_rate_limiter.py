# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for HostRateLimiter (ingestion module)."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from modules.ingestion.fetching.rate_limiter import HostRateLimiter


class TestHostRateLimiterInit:
    """Test HostRateLimiter initialization."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        limiter = HostRateLimiter()

        assert limiter._delay_min == 1.0
        assert limiter._delay_max == 3.0

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        limiter = HostRateLimiter(delay_min=0.5, delay_max=2.0)

        assert limiter._delay_min == 0.5
        assert limiter._delay_max == 2.0

    def test_init_internal_state(self):
        """Test initialization of internal state."""
        limiter = HostRateLimiter()

        assert limiter._last_request == {}
        assert limiter._locks == {}


class TestHostRateLimiterAcquire:
    """Test HostRateLimiter.acquire method."""

    def test_acquire_returns_float(self):
        """Test acquire returns a float."""
        limiter = HostRateLimiter()

        async def run_test():
            result = await limiter.acquire("https://example.com/page")
            assert isinstance(result, float)

        asyncio.run(run_test())

    def test_acquire_first_request_no_wait(self):
        """Test first request to a host requires no wait."""
        limiter = HostRateLimiter()

        async def run_test():
            result = await limiter.acquire("https://example.com/page")
            # First request should return 0 (no wait)
            assert result == 0.0

        asyncio.run(run_test())

    def test_acquire_different_hosts_no_wait(self):
        """Test requests to different hosts don't wait for each other."""
        limiter = HostRateLimiter(delay_min=0.01, delay_max=0.02)

        async def run_test():
            result1 = await limiter.acquire("https://example.com/page1")
            result2 = await limiter.acquire("https://other.com/page1")

            # Different hosts should both return 0
            assert result1 == 0.0
            assert result2 == 0.0

        asyncio.run(run_test())

    def test_acquire_same_host_waits(self):
        """Test requests to same host trigger wait."""
        limiter = HostRateLimiter(delay_min=0.1, delay_max=0.1)

        async def run_test():
            # First request
            result1 = await limiter.acquire("https://example.com/page1")
            assert result1 == 0.0

            # Second request should wait
            result2 = await limiter.acquire("https://example.com/page2")
            assert result2 > 0

        asyncio.run(run_test())

    def test_acquire_updates_last_request_time(self):
        """Test acquire updates the last request time for host."""
        limiter = HostRateLimiter()

        async def run_test():
            await limiter.acquire("https://example.com/page1")

            assert "example.com" in limiter._last_request
            assert limiter._last_request["example.com"] > 0

        asyncio.run(run_test())

    def test_acquire_concurrent_requests_serialized(self):
        """Test concurrent requests to same host are serialized."""
        limiter = HostRateLimiter(delay_min=0.05, delay_max=0.05)

        async def run_test():
            # Make two concurrent requests
            start = time.monotonic()
            await asyncio.gather(
                limiter.acquire("https://example.com/page1"),
                limiter.acquire("https://example.com/page2"),
            )
            elapsed = time.monotonic() - start

            # Both requests should take at least 0.05s total due to serialization
            assert elapsed >= 0.04  # Allow small margin

        asyncio.run(run_test())


class TestHostRateLimiterUrlParser:
    """Test that HostRateLimiter correctly parses URLs for host extraction."""

    def test_acquire_http_url(self):
        """Test acquire with HTTP URL."""
        limiter = HostRateLimiter()

        async def run_test():
            await limiter.acquire("http://example.com/page")
            assert "example.com" in limiter._last_request

        asyncio.run(run_test())

    def test_acquire_https_url(self):
        """Test acquire with HTTPS URL."""
        limiter = HostRateLimiter()

        async def run_test():
            await limiter.acquire("https://example.com/page")
            assert "example.com" in limiter._last_request

        asyncio.run(run_test())

    def test_acquire_url_with_port(self):
        """Test acquire with URL containing port."""
        limiter = HostRateLimiter()

        async def run_test():
            await limiter.acquire("https://example.com:8080/page")
            assert "example.com:8080" in limiter._last_request

        asyncio.run(run_test())

    def test_acquire_url_with_subdomain(self):
        """Test acquire with URL containing subdomain."""
        limiter = HostRateLimiter()

        async def run_test():
            await limiter.acquire("https://sub.example.com/page")
            assert "sub.example.com" in limiter._last_request

        asyncio.run(run_test())
