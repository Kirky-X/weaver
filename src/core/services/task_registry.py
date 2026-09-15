# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""In-memory task registry for background task tracking."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from core.constants import TaskStatus
from core.observability import get_logger

log = get_logger(__name__)


class InMemoryTaskRegistry:
    """In-memory implementation of TaskRegistryService.

    Tracks background tasks started by API endpoints, enabling status
    queries and cancellation.

    Implements: TaskRegistryService
    """

    def __init__(self) -> None:
        """Initialize the task registry."""
        self._tasks: dict[str, dict[str, Any]] = {}

    async def register(
        self,
        task_id: str,
        task: Any,  # Coroutine[Any, Any, Any]
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a background task.

        Args:
            task_id: Unique identifier for the task.
            task: The coroutine to track.
            metadata: Optional metadata about the task.
        """
        if task_id in self._tasks:
            log.warning("task_already_registered", task_id=task_id)
            return

        # Create task from coroutine
        async_task = asyncio.create_task(task)

        self._tasks[task_id] = {
            "task": async_task,
            "metadata": metadata or {},
            "status": TaskStatus.RUNNING.value,
            "result": None,
            "error": None,
        }

        log.info("task_registered", task_id=task_id, metadata=metadata)

        # Set up completion callback
        def on_done(t: asyncio.Task) -> None:
            entry = self._tasks.get(task_id)
            if entry is None:
                return
            completed_at = time.time()
            try:
                entry["result"] = t.result()
                entry["status"] = TaskStatus.DONE.value
                entry["completed_at"] = completed_at
                log.debug("task_completed", task_id=task_id)
            except asyncio.CancelledError:
                entry["status"] = TaskStatus.CANCELLED.value
                entry["completed_at"] = completed_at
                log.debug("task_cancelled", task_id=task_id)
            except Exception as e:
                entry["error"] = str(e)
                entry["status"] = TaskStatus.FAILED.value
                entry["completed_at"] = completed_at
                log.error("task_failed", task_id=task_id, error=str(e))

        async_task.add_done_callback(on_done)
        # Bound memory: production never calls cleanup_completed(), so prune
        # the oldest terminal-state entries here or the dict grows forever.
        self._prune_terminal_entries()

    def _prune_terminal_entries(self, max_terminal: int = 500) -> int:
        """Drop oldest DONE/CANCELLED/FAILED entries beyond ``max_terminal``."""
        terminal_states = (
            TaskStatus.DONE.value,
            TaskStatus.CANCELLED.value,
            TaskStatus.FAILED.value,
        )
        terminal_ids = [
            tid for tid, entry in self._tasks.items() if entry.get("status") in terminal_states
        ]
        overflow = len(terminal_ids) - max_terminal
        if overflow <= 0:
            return 0
        # Dict preserves insertion order — oldest registrations come first.
        for tid in terminal_ids[:overflow]:
            self._tasks.pop(tid, None)
        log.debug("task_registry_pruned", count=overflow)
        return overflow

    async def get_status(self, task_id: str) -> dict[str, Any]:
        """Get the status of a registered task.

        Args:
            task_id: The task ID to query.

        Returns:
            Status dict with 'status', 'result', 'error', 'metadata' fields.
        """
        entry = self._tasks.get(task_id)
        if entry is None:
            return {
                "status": TaskStatus.NOT_FOUND.value,
                "result": None,
                "error": None,
                "metadata": {},
            }

        return {
            "status": entry["status"],
            "result": entry["result"],
            "error": entry["error"],
            "metadata": entry["metadata"],
        }

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: The task ID to cancel.

        Returns:
            True if task was cancelled, False if not found or already done.
        """
        entry = self._tasks.get(task_id)
        if entry is None:
            return False

        task = entry.get("task")
        if task is None or task.done():
            return False

        task.cancel()
        entry["status"] = TaskStatus.CANCELLED.value
        log.info("task_cancelled_by_request", task_id=task_id)
        return True

    async def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List registered tasks.

        Args:
            status: Filter by status (running, done, cancelled, failed).
                ``pending`` 不是合法取值——TaskStatus 未定义 PENDING，任务注册时
                直接处于 RUNNING 状态。
            limit: Maximum number of tasks to return.

        Returns:
            List of task status dicts.
        """
        results = []
        for task_id, entry in self._tasks.items():
            if status is not None and entry["status"] != status:
                continue
            results.append(
                {
                    "task_id": task_id,
                    "status": entry["status"],
                    "metadata": entry["metadata"],
                }
            )
            if len(results) >= limit:
                break
        return results

    async def cleanup_completed(self, max_age_seconds: int = 3600) -> int:
        """Remove completed tasks older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age of completed tasks to keep.

        Returns:
            Number of tasks removed.
        """
        # Remove done/cancelled/failed tasks older than max_age_seconds
        current_time = time.time()
        to_remove = [
            tid
            for tid, entry in self._tasks.items()
            if entry["status"]
            in (TaskStatus.DONE.value, TaskStatus.CANCELLED.value, TaskStatus.FAILED.value)
            and (current_time - entry.get("completed_at", current_time)) > max_age_seconds
        ]
        for tid in to_remove:
            del self._tasks[tid]

        if to_remove:
            log.info("tasks_cleaned_up", count=len(to_remove))

        return len(to_remove)
