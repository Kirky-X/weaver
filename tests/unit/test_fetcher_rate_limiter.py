"""Unit tests for HostRateLimiter."""

import asyncio
import time

import pytest

from modules.fetcher.rate_limiter import HostRateLimiter


class TestHostRateLimiterInit:
    """Test HostRateLimiter initialization."""

    def test_default_init(self):
        """Test default initialization."""
        limiter = HostRateLimiter()
        assert limiter._delay_min == 1.0
        assert limiter._delay_max == 3.0

    def test_custom_init(self):
        """Test custom initialization."""
        limiter = HostRateLimiter(delay_min=0.5, delay_max=2.0)
        assert limiter._delay_min == 0.5
        assert limiter._delay_max == 2.0


class TestHostRateLimiterAcquire:
    """Test HostRateLimiter.acquire method."""

    @pytest.mark.asyncio
    async def test_first_request_no_delay(self):
        """Test that first request has no delay."""
        limiter = HostRateLimiter(delay_min=1.0, delay_max=3.0)

        start = time.monotonic()
        wait_time = await limiter.acquire("https://example.com/page1")
        elapsed = time.monotonic() - start

        assert wait_time == 0.0
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_consecutive_requests_have_delay(self):
        """Test that consecutive requests to same host have delay."""
        limiter = HostRateLimiter(delay_min=0.1, delay_max=0.2)

        url = "https://example.com/page1"

        await limiter.acquire(url)

        start = time.monotonic()
        wait_time = await limiter.acquire(url)
        elapsed = time.monotonic() - start

        assert wait_time > 0
        assert elapsed >= 0.1

    @pytest.mark.asyncio
    async def test_different_hosts_no_delay(self):
        """Test that requests to different hosts have no delay."""
        limiter = HostRateLimiter(delay_min=1.0, delay_max=3.0)

        await limiter.acquire("https://example.com/page1")

        start = time.monotonic()
        wait_time = await limiter.acquire("https://other.com/page1")
        elapsed = time.monotonic() - start

        assert wait_time == 0.0
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_delay_is_random(self):
        """Test that delay varies between requests."""
        limiter = HostRateLimiter(delay_min=0.1, delay_max=0.3)

        url = "https://example.com/page1"
        wait_times = []

        for _ in range(5):
            await limiter.acquire(url)
            start = time.monotonic()
            await limiter.acquire(url)
            wait_times.append(time.monotonic() - start)

        assert len(set(round(w, 2) for w in wait_times)) > 1

    @pytest.mark.asyncio
    async def test_delay_respects_max(self):
        """Test that delay does not exceed max."""
        limiter = HostRateLimiter(delay_min=0.1, delay_max=0.2)

        url = "https://example.com/page1"

        for _ in range(3):
            await limiter.acquire(url)
            start = time.monotonic()
            await limiter.acquire(url)
            elapsed = time.monotonic() - start
            assert elapsed < 0.35

    @pytest.mark.asyncio
    async def test_concurrent_requests_same_host(self):
        """Test that concurrent requests to same host are serialized."""
        limiter = HostRateLimiter(delay_min=0.1, delay_max=0.2)

        url = "https://example.com/page1"

        start = time.monotonic()
        results = await asyncio.gather(
            limiter.acquire(url),
            limiter.acquire(url),
            limiter.acquire(url),
        )
        elapsed = time.monotonic() - start

        assert sum(r for r in results if r > 0) > 0
        assert elapsed >= 0.2

    @pytest.mark.asyncio
    async def test_concurrent_requests_different_hosts(self):
        """Test that concurrent requests to different hosts run in parallel."""
        limiter = HostRateLimiter(delay_min=0.5, delay_max=1.0)

        start = time.monotonic()
        results = await asyncio.gather(
            limiter.acquire("https://host1.com/page"),
            limiter.acquire("https://host2.com/page"),
            limiter.acquire("https://host3.com/page"),
        )
        elapsed = time.monotonic() - start

        assert all(r == 0.0 for r in results)
        assert elapsed < 0.5
