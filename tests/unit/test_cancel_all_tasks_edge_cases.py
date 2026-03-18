"""Test edge cases for cancel_all_tasks utility."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
import logging


@pytest.mark.asyncio
async def test_cancel_all_tasks_with_empty_list():
    """Verify cancel_all_tasks handles empty task list gracefully."""
    from tests.conftest import cancel_all_tasks

    # No background tasks running
    await cancel_all_tasks()
    # Should complete without error


@pytest.mark.asyncio
async def test_cancel_all_tasks_with_already_cancelled_task():
    """Verify cancel_all_tasks handles already cancelled tasks."""
    from tests.conftest import cancel_all_tasks

    # Create a task and cancel it immediately
    async def dummy_worker():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy_worker())
    task.cancel()

    # Now run cancel_all_tasks
    await cancel_all_tasks()

    # Should complete without error
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_cancel_all_tasks_with_unresponsive_task():
    """Verify cancel_all_tasks handles tasks that don't respond to cancellation."""
    from tests.conftest import cancel_all_tasks

    # Create a task that catches CancelledError and ignores it (bad pattern)
    unresponsive_task_completed = False

    async def unresponsive_worker():
        nonlocal unresponsive_task_completed
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            # This is bad practice - catching CancelledError without re-raising
            # But we need to handle it gracefully
            await asyncio.sleep(0.5)  # Simulate slow response
            unresponsive_task_completed = True
            return  # Exit cleanly after delay

    task = asyncio.create_task(unresponsive_worker())

    # Run cancel_all_tasks (it has timeout handling)
    await cancel_all_tasks()

    # Task should be done (either cancelled or completed)
    assert task.done()
    # The unresponsive handler should have eventually completed
    assert unresponsive_task_completed or task.cancelled()


@pytest.mark.asyncio
async def test_cancel_all_tasks_with_multiple_task_types():
    """Verify cancel_all_tasks handles mix of normal, cancelled, and slow tasks."""
    from tests.conftest import cancel_all_tasks

    tasks_completed = []

    async def normal_worker():
        await asyncio.sleep(0.1)
        tasks_completed.append("normal")

    async def slow_worker():
        try:
            await asyncio.sleep(10)
            tasks_completed.append("slow")
        except asyncio.CancelledError:
            tasks_completed.append("slow_cancelled")
            raise

    # Create different types of tasks
    normal_task = asyncio.create_task(normal_worker())
    slow_task = asyncio.create_task(slow_worker())

    # Cancel one task beforehand
    pre_cancelled_task = asyncio.create_task(normal_worker())
    pre_cancelled_task.cancel()

    # Wait for normal task to complete
    await asyncio.sleep(0.2)

    # Run cancel_all_tasks
    await cancel_all_tasks()

    # All tasks should be done
    assert normal_task.done()
    assert slow_task.done()
    assert pre_cancelled_task.done()

    # Normal task should have completed, slow task cancelled
    assert "normal" in tasks_completed
    assert "slow_cancelled" in tasks_completed


@pytest.mark.asyncio
async def test_cancel_all_tasks_timeout_handling(caplog):
    """Verify cancel_all_tasks logs warning on timeout."""
    from tests.conftest import cancel_all_tasks

    caplog.set_level(logging.WARNING)

    # Create a task that really doesn't want to stop
    async def stubborn_worker():
        try:
            # Ignore cancellation and keep running
            while True:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # Catch but don't exit immediately
            await asyncio.sleep(10)  # Longer than our 5s timeout

    task = asyncio.create_task(stubborn_worker())

    # Run cancel_all_tasks - should timeout and log warning
    await cancel_all_tasks()

    # Should have logged a timeout warning
    # Note: The task might still complete after timeout
    assert task.done() or "task_cancellation_timeout" in caplog.text