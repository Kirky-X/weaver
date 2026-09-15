# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 KirkyX. All Rights Reserved.
"""Concurrency tests for RequestDelay.BoundedLockDict (CORR#244 family).

Mirrors the fix in modules/ingestion/fetching/rate_limiter.py: busy locks
must never be evicted, otherwise two coroutines can pass the critical
section for the same provider and the minimum delay collapses to ~0.
"""

from __future__ import annotations

import asyncio
import time
from itertools import pairwise
from unittest.mock import patch

import pytest

from core.llm.resilience.request_delay import BoundedLockDict, RequestDelay


class TestBoundedLockDictEvictionSafety:
    @pytest.mark.asyncio
    async def test_busy_lock_is_not_evicted(self):
        d = BoundedLockDict(maxsize=2)
        held = d["a"]
        await held.acquire()  # busy

        d["b"]  # second entry

        # Adding a third key must not evict the held lock "a"
        d["c"]

        assert "a" in d
        assert d["a"] is held
        held.release()

    def test_in_flight_lock_is_not_evicted_between_get_and_acquire(self):
        d = BoundedLockDict(maxsize=2)
        _ = d["a"]
        d.mark_in_flight("a")

        d["b"]
        d["c"]  # capacity reached — "a" is in flight but not locked yet

        assert "a" in d
        d.mark_done("a")

    @pytest.mark.asyncio
    async def test_idle_lock_evicted_first(self):
        d = BoundedLockDict(maxsize=2)
        idle = d["a"]
        busy = d["b"]
        await busy.acquire()
        d.mark_in_flight("b")

        d["c"]  # must evict idle "a", not busy "b"

        assert "a" not in d
        assert "b" in d
        busy.release()

    @pytest.mark.asyncio
    async def test_over_capacity_allowed_when_all_busy(self):
        d = BoundedLockDict(maxsize=1)
        lock_a = d["a"]
        await lock_a.acquire()
        d.mark_in_flight("a")

        lock_b = d["b"]  # nothing evictable — must not return lock_a

        assert lock_b is not lock_a
        assert len(d) == 2  # temporarily over capacity
        d.mark_done("a")
        lock_a.release()


class TestRequestDelayConcurrency:
    async def _drive(self, delay: RequestDelay, provider: str, n: int) -> list[float]:
        return list(await asyncio.gather(*[delay.acquire(provider) for _ in range(n)]))

    async def test_concurrent_acquires_serialized_per_provider(self):
        """N concurrent acquires must produce N spaced timestamps.

        Without the eviction-safety fix, capacity pressure could evict the
        lock mid-flight and let two coroutines read the same last_time,
        collapsing the serialized spacing.
        """
        delay = RequestDelay(enabled=True, delay_min=0.01, delay_max=0.02)
        # Force eviction pressure with a tiny lock cache
        delay._locks = BoundedLockDict(maxsize=1)
        # Flood the cache with another provider so "hot" gets evicted when
        # a cold provider arrives mid-flight.
        timestamps: list[float] = []

        with patch("core.llm.resilience.request_delay.random.uniform", return_value=0.02):
            await delay.acquire("other")  # create "other" entry

            async def acquire_and_record():
                await delay.acquire("hot")
                timestamps.append(time.monotonic())

            await asyncio.gather(*[acquire_and_record() for _ in range(5)])

        assert len(timestamps) == 5
        # Each request must start at least delay_min after the previous one
        timestamps.sort()
        for prev, curr in pairwise(timestamps):
            assert curr - prev >= 0.009, (prev, curr)

    async def test_disabled_returns_immediately(self):
        delay = RequestDelay(enabled=False)
        assert await delay.acquire("p") == 0.0

    async def test_mark_done_releases_in_flight(self):
        delay = RequestDelay(enabled=True, delay_min=0.0, delay_max=0.0)
        await delay.acquire("p")
        assert "p" not in delay._locks._in_flight
