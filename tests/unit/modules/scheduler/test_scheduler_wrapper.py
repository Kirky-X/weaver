# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for the scheduled_task decorator."""

from __future__ import annotations

import asyncio

import pytest

from modules.scheduler.wrapper import scheduled_task


@pytest.mark.asyncio
async def test_scheduled_task_success():
    """Decorator logs and metrics on success."""

    @scheduled_task("test_job", timeout_seconds=5)
    async def my_job():
        return 42

    result = await my_job()
    assert result == 42


@pytest.mark.asyncio
async def test_scheduled_task_timeout():
    """Decorator returns 0 on timeout."""

    @scheduled_task("timeout_job", timeout_seconds=0)
    async def slow_job():
        await asyncio.sleep(10)
        return 99

    result = await slow_job()
    assert result == 0


@pytest.mark.asyncio
async def test_scheduled_task_error():
    """Decorator returns 0 on exception."""

    @scheduled_task("error_job", timeout_seconds=5)
    async def failing_job():
        raise ValueError("boom")

    result = await failing_job()
    assert result == 0


@pytest.mark.asyncio
async def test_scheduled_task_preserves_function_name():
    """Decorator preserves the original function name."""

    @scheduled_task("name_job")
    async def my_named_job():
        return 1

    assert my_named_job.__name__ == "my_named_job"
