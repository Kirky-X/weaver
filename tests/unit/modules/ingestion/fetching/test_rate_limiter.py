# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for HostRateLimiter (ingestion module)."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest
from cachetools import LRUCache

from modules.ingestion.fetching.rate_limiter import BoundedLockDict, HostRateLimiter


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
        """Test initialization of internal state with bounded containers."""
        limiter = HostRateLimiter()

        # Now uses bounded containers to prevent memory leaks
        assert isinstance(limiter._last_request, LRUCache)
        assert limiter._last_request.maxsize == 1000
        assert len(limiter._last_request) == 0

        assert isinstance(limiter._locks, BoundedLockDict)
        assert limiter._locks._maxsize == 1000
        assert len(limiter._locks) == 0


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


class TestBoundedLockDictWaiterAwareEviction:
    """CORR#244: eviction must not drop a lock that is held or awaited.

    ``locked()`` alone misses the release→waiter-resumption window; the
    in-flight counter covers holders and queued waiters alike.
    """

    def test_eviction_skips_in_flight_key(self):
        """A key marked in-flight is never chosen for eviction."""
        d = BoundedLockDict(maxsize=2)
        lock_a = d["a"]
        lock_b = d["b"]
        d.mark_in_flight("a")  # holder/waiter registered before lookup

        _ = d["c"]  # capacity reached — must evict b (idle), not a

        assert "a" in d
        assert "b" not in d
        assert "c" in d
        assert d["a"] is lock_a
        assert lock_a.locked() is False  # untouched

    def test_eviction_all_locks_in_flight_over_capacity(self):
        """When every lock is in-flight, none is evicted (over-capacity)."""
        d = BoundedLockDict(maxsize=2)
        d["a"]
        d["b"]
        d.mark_in_flight("a")
        d.mark_in_flight("b")

        _ = d["c"]

        assert len(d) == 3  # temporary over-capacity, nothing lost

    def test_mark_done_allows_eviction_again(self):
        """After the caller finishes, the lock becomes evictable."""
        d = BoundedLockDict(maxsize=1)
        d["a"]
        d.mark_in_flight("a")
        d.mark_done("a")

        _ = d["b"]

        assert "a" not in d
        assert "b" in d

    def test_mark_done_balances_concurrent_waiters(self):
        """Multiple waiters on one key: lock survives until the last is done.

        Note: never read ``d["a"]`` mid-test — ``__getitem__`` refreshes the
        LRU order and would change which key is the eviction candidate.
        """
        d = BoundedLockDict(maxsize=2)
        lock_a = d["a"]
        d.mark_in_flight("a")
        d.mark_in_flight("a")  # second waiter queued

        d.mark_done("a")  # 1 waiter still pending — a stays protected
        d["b"]
        d["c"]  # capacity reached — evicts b (LRU), skips in-flight a
        assert "a" in d
        assert d._locks["a"] is lock_a

        d.mark_done("a")  # last waiter done — a is now evictable
        d["d"]  # a is the LRU head again — evicted
        assert "a" not in d

    def test_acquire_cleans_up_in_flight_on_wait_and_success(self):
        """HostRateLimiter.acquire registers and releases the in-flight mark."""
        limiter = HostRateLimiter(delay_min=0.01, delay_max=0.01)

        async def run_test():
            await limiter.acquire("https://example.com/page1")
            await limiter.acquire("https://example.com/page2")  # triggers wait path

            assert len(limiter._locks._in_flight) == 0

        asyncio.run(run_test())

    def test_acquire_in_flight_tracks_held_lock(self):
        """While a coroutine holds the host lock, the key stays in-flight."""
        limiter = HostRateLimiter(delay_min=0.05, delay_max=0.05)

        async def run_test():
            # First request: no wait, just seeds last_request.
            await limiter.acquire("https://example.com/p1")
            # Second request enters the wait path and sleeps while holding
            # the host lock.
            holder_task = asyncio.create_task(limiter.acquire("https://example.com/p2"))
            while not limiter._locks["example.com"].locked() and not holder_task.done():
                await asyncio.sleep(0)

            assert limiter._locks["example.com"].locked()
            assert limiter._locks._in_flight.get("example.com", 0) >= 1

            await holder_task
            assert len(limiter._locks._in_flight) == 0

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
