# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for the scheduled_task decorator."""

from __future__ import annotations

import asyncio

import pytest

from modules.scheduler import scheduled_task


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
    """Decorator returns -1 on timeout."""

    @scheduled_task("timeout_job", timeout_seconds=0)
    async def slow_job():
        await asyncio.sleep(10)
        return 99

    result = await slow_job()
    assert result == -1


@pytest.mark.asyncio
async def test_scheduled_task_error():
    """Decorator returns -2 on exception."""

    @scheduled_task("error_job", timeout_seconds=5)
    async def failing_job():
        raise ValueError("boom")

    result = await failing_job()
    assert result == -2


@pytest.mark.asyncio
async def test_scheduled_task_preserves_function_name():
    """Decorator preserves the original function name."""

    @scheduled_task("name_job")
    async def my_named_job():
        return 1

    assert my_named_job.__name__ == "my_named_job"


@pytest.mark.asyncio
async def test_timeout_records_the_real_exception():
    """#269: the timeout branch must pass the caught TimeoutError to the span."""
    from unittest.mock import MagicMock, patch

    from modules.scheduler import wrapper as wrapper_module

    span = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=span)
    ctx.__exit__ = MagicMock(return_value=False)

    @wrapper_module.scheduled_task("t008_timeout_job", timeout_seconds=0)
    async def slow_job():
        await asyncio.sleep(10)
        return 99

    with patch.object(wrapper_module.tracer, "start_as_current_span", return_value=ctx):
        assert await slow_job() == -1

    recorded = [c.args[0] for c in span.record_exception.call_args_list]
    assert recorded, "record_exception must be called"
    assert isinstance(recorded[0], TimeoutError)
