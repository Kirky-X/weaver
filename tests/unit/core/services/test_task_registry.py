# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for InMemoryTaskRegistry."""

from __future__ import annotations

import asyncio

import pytest

from core.services.task_registry import InMemoryTaskRegistry


@pytest.fixture
def registry() -> InMemoryTaskRegistry:
    """Create a fresh InMemoryTaskRegistry instance."""
    return InMemoryTaskRegistry()


class TestInMemoryTaskRegistry:
    """Tests for InMemoryTaskRegistry."""

    async def test_register_task(self, registry: InMemoryTaskRegistry) -> None:
        """Test registering a background task."""

        async def sample_task() -> str:
            await asyncio.sleep(0.01)
            return "completed"

        await registry.register("task-1", sample_task(), {"type": "test"})

        status = await registry.get_status("task-1")
        assert status["status"] in ("running", "done")
        assert status["metadata"] == {"type": "test"}

    async def test_get_status_not_found(self, registry: InMemoryTaskRegistry) -> None:
        """Test getting status for non-existent task."""
        status = await registry.get_status("non-existent")

        assert status["status"] == "not_found"
        assert status["result"] is None
        assert status["error"] is None

    async def test_task_completion(self, registry: InMemoryTaskRegistry) -> None:
        """Test that task status updates on completion."""

        async def quick_task() -> str:
            return "done"

        await registry.register("quick-task", quick_task())

        # Wait for task to complete
        await asyncio.sleep(0.1)

        status = await registry.get_status("quick-task")
        assert status["status"] == "done"
        assert status["result"] == "done"

    async def test_task_failure(self, registry: InMemoryTaskRegistry) -> None:
        """Test that task status updates on failure."""

        async def failing_task() -> None:
            raise ValueError("Task failed intentionally")

        await registry.register("failing-task", failing_task())

        # Wait for task to complete
        await asyncio.sleep(0.1)

        status = await registry.get_status("failing-task")
        assert status["status"] == "failed"
        assert "Task failed intentionally" in status["error"]

    async def test_cancel_running_task(self, registry: InMemoryTaskRegistry) -> None:
        """Test cancelling a running task."""

        async def long_task() -> str:
            await asyncio.sleep(10)  # Long running
            return "completed"

        await registry.register("long-task", long_task())

        # Cancel immediately
        cancelled = await registry.cancel("long-task")
        assert cancelled is True

        status = await registry.get_status("long-task")
        assert status["status"] == "cancelled"

    async def test_cancel_nonexistent_task(self, registry: InMemoryTaskRegistry) -> None:
        """Test cancelling a task that doesn't exist."""
        cancelled = await registry.cancel("non-existent")
        assert cancelled is False

    async def test_cancel_completed_task(self, registry: InMemoryTaskRegistry) -> None:
        """Test that cancelling a completed task returns False."""

        async def quick_task() -> str:
            return "done"

        await registry.register("quick-task", quick_task())
        await asyncio.sleep(0.1)  # Wait for completion

        cancelled = await registry.cancel("quick-task")
        assert cancelled is False

    async def test_list_tasks(self, registry: InMemoryTaskRegistry) -> None:
        """Test listing registered tasks."""

        async def task1() -> str:
            await asyncio.sleep(0.1)
            return "done1"

        async def task2() -> str:
            await asyncio.sleep(0.1)
            return "done2"

        await registry.register("task-1", task1(), {"type": "test"})
        await registry.register("task-2", task2(), {"type": "production"})

        tasks = await registry.list_tasks()
        assert len(tasks) == 2

        task_ids = {t["task_id"] for t in tasks}
        assert "task-1" in task_ids
        assert "task-2" in task_ids

    async def test_list_tasks_with_status_filter(self, registry: InMemoryTaskRegistry) -> None:
        """Test listing tasks filtered by status."""

        async def quick_task() -> str:
            return "done"

        async def failing_task() -> None:
            raise RuntimeError("fail")

        await registry.register("done-task", quick_task())
        await registry.register("fail-task", failing_task())

        await asyncio.sleep(0.2)  # Wait for completion

        done_tasks = await registry.list_tasks(status="done")
        assert len(done_tasks) == 1
        assert done_tasks[0]["task_id"] == "done-task"

        failed_tasks = await registry.list_tasks(status="failed")
        assert len(failed_tasks) == 1
        assert failed_tasks[0]["task_id"] == "fail-task"

    async def test_list_tasks_with_limit(self, registry: InMemoryTaskRegistry) -> None:
        """Test listing tasks with a limit."""

        async def task() -> str:
            await asyncio.sleep(0.5)
            return "done"

        for i in range(5):
            await registry.register(f"task-{i}", task(), {"index": i})

        tasks = await registry.list_tasks(limit=3)
        assert len(tasks) == 3

    async def test_cleanup_completed(self, registry: InMemoryTaskRegistry) -> None:
        """Test cleaning up completed tasks."""

        async def quick_task() -> str:
            return "done"

        async def failing_task() -> None:
            raise RuntimeError("fail")

        async def long_task() -> str:
            await asyncio.sleep(10)
            return "done"

        await registry.register("done-task", quick_task())
        await registry.register("fail-task", failing_task())
        await registry.register("running-task", long_task())

        await asyncio.sleep(0.2)  # Wait for quick tasks to complete

        removed = await registry.cleanup_completed()
        assert removed == 2  # done-task and fail-task

        # Running task should still exist
        status = await registry.get_status("running-task")
        assert status["status"] == "running"

    async def test_register_duplicate_task_id(self, registry: InMemoryTaskRegistry) -> None:
        """Test that registering with duplicate ID is ignored."""

        async def task1() -> str:
            return "first"

        async def task2() -> str:
            return "second"

        await registry.register("same-id", task1(), {"version": 1})
        await registry.register("same-id", task2(), {"version": 2})

        status = await registry.get_status("same-id")
        assert status["metadata"] == {"version": 1}  # First registration wins
