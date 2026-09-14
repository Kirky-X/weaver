# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for scheduler distributed lock (T013)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.cache.distributed_lock import (
    distributed_lock,
    trigger_interval_seconds,
    wrap_scheduler_with_lock,
)


def _pool_with_setnx(acquired: bool = True) -> MagicMock:
    pool = MagicMock()
    pool.set_nx = AsyncMock(return_value=acquired)
    pool.get = AsyncMock(return_value=None)
    pool.delete = AsyncMock(return_value=True)
    return pool


class TestDistributedLockDecorator:
    @pytest.mark.asyncio
    async def test_acquired_lock_runs_function(self) -> None:
        pool = _pool_with_setnx(acquired=True)
        pool.get = AsyncMock(return_value="inst-1")

        @distributed_lock(
            "weaver:scheduler:job", ttl_seconds=60, cache_pool=pool, instance_id="inst-1"
        )
        async def job() -> str:
            return "ran"

        assert await job() == "ran"
        args, kwargs = pool.set_nx.await_args
        assert args[0] == "weaver:scheduler:job"
        assert kwargs.get("ex") == 60
        pool.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unacquired_lock_skips_function(self) -> None:
        pool = _pool_with_setnx(acquired=False)
        calls: list[str] = []

        @distributed_lock("weaver:scheduler:job", ttl_seconds=60, cache_pool=pool)
        async def job() -> None:
            calls.append("ran")

        result = await job()

        assert result is None
        assert calls == []

    @pytest.mark.asyncio
    async def test_release_only_when_holder(self) -> None:
        pool = _pool_with_setnx(acquired=True)
        pool.get = AsyncMock(return_value="other-instance")

        @distributed_lock(
            "weaver:scheduler:job", ttl_seconds=60, cache_pool=pool, instance_id="inst-1"
        )
        async def job() -> None: ...

        await job()

        pool.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pool_without_setnx_runs_unprotected_with_warning(self) -> None:
        pool = MagicMock(spec=["get", "delete"])  # no set_nx (degraded mode)
        calls: list[str] = []

        @distributed_lock("weaver:scheduler:job", ttl_seconds=60, cache_pool=pool)
        async def job() -> None:
            calls.append("ran")

        await job()

        assert calls == ["ran"]

    @pytest.mark.asyncio
    async def test_function_exception_still_releases_lock(self) -> None:
        pool = _pool_with_setnx(acquired=True)
        pool.get = AsyncMock(return_value="inst-1")

        @distributed_lock(
            "weaver:scheduler:job", ttl_seconds=60, cache_pool=pool, instance_id="inst-1"
        )
        async def job() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await job()

        pool.delete.assert_awaited_once()


class TestTriggerInterval:
    def test_interval_trigger_seconds(self) -> None:
        from apscheduler.triggers.interval import IntervalTrigger

        trigger = IntervalTrigger(minutes=10)
        assert trigger_interval_seconds(trigger) == 600.0

    def test_cron_trigger_has_no_interval(self) -> None:
        from apscheduler.triggers.cron import CronTrigger

        assert trigger_interval_seconds(CronTrigger(hour=3)) is None


class TestWrapScheduler:
    def test_all_jobs_wrapped_with_lock_and_ttl(self) -> None:
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = MagicMock()
        registered: list = []
        scheduler.add_job = lambda fn, trigger, *a, **kw: registered.append((fn, trigger, kw))

        wrap_scheduler_with_lock(scheduler, _pool_with_setnx())

        jobs = MagicMock()
        jobs.sync_job = AsyncMock()
        jobs.cron_job = AsyncMock()
        scheduler.add_job(jobs.sync_job, IntervalTrigger(minutes=10), id="sync_job", name="s")
        scheduler.add_job(jobs.cron_job, CronTrigger(hour=1), id="cron_job", max_instances=1)

        assert len(registered) == 2
        for fn, _trigger, kwargs in registered:
            assert kwargs["id"] in {"sync_job", "cron_job"}
            # wrapped coroutines remain awaitable
            assert hasattr(fn, "__wrapped__")

    def test_interval_ttl_is_80_percent_capped(self) -> None:
        """10-minute job gets an 8-minute (480s) lock TTL."""
        from apscheduler.triggers.interval import IntervalTrigger

        pool = _pool_with_setnx()
        captured: dict = {}

        real_pool = MagicMock()
        real_pool.set_nx = AsyncMock(return_value=True)
        real_pool.get = AsyncMock(return_value=None)
        real_pool.delete = AsyncMock()

        def capture(name: str, ttl_seconds: int = 3600, cache_pool=None):
            captured["ttl"] = ttl_seconds

            def decorator(fn):
                return fn

            return decorator

        scheduler = MagicMock()
        scheduler.add_job = lambda fn, trigger, *a, **kw: None

        import core.cache.distributed_lock as dl

        original = dl.distributed_lock
        dl.distributed_lock = capture
        try:
            wrap_scheduler_with_lock(scheduler, real_pool)
            scheduler.add_job(AsyncMock(), IntervalTrigger(minutes=10), id="sync_job")
        finally:
            dl.distributed_lock = original

        assert captured["ttl"] == 480
