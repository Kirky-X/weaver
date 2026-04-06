# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Service layer protocol definitions for cross-module communication.

This module defines Protocol classes for service layer interfaces that
enable loose coupling between modules. Services encapsulate business logic
and provide stable interfaces for other modules to depend on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Coroutine


@runtime_checkable
class PipelineService(Protocol):
    """Protocol for pipeline processing service.

    This service provides a stable interface for modules that need to
    trigger pipeline processing without depending on internal implementation.

    Implementations:
        - PipelineServiceImpl: Wraps PipelineGraph with a service interface
    """

    async def run_phase3_per_article(
        self,
        article_id: str,
        *,
        force_reprocess: bool = False,
    ) -> dict[str, Any]:
        """Run phase 3 processing for a single article.

        Args:
            article_id: The article ID to process.
            force_reprocess: Force reprocessing even if already processed.

        Returns:
            Processing result with entity extraction status.

        Raises:
            ArticleNotFoundError: If article does not exist.
            ProcessingError: If processing fails.
        """
        ...

    async def get_pipeline_status(self, article_id: str) -> dict[str, Any]:
        """Get the processing status for an article.

        Args:
            article_id: The article ID to check.

        Returns:
            Status dict with phase completion flags.
        """
        ...

    async def run_full_pipeline(
        self,
        url: str,
        *,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        """Run the complete pipeline for a URL.

        Args:
            url: URL to process.
            source_name: Optional source name override.

        Returns:
            Processing result with article ID and status.
        """
        ...


@runtime_checkable
class TaskRegistryService(Protocol):
    """Protocol for background task tracking.

    This service provides a way to track, query, and cancel background
    tasks started by API endpoints.

    Implementations:
        - InMemoryTaskRegistry: In-memory task tracking
    """

    async def register(
        self,
        task_id: str,
        task: Coroutine[Any, Any, Any],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a background task.

        Args:
            task_id: Unique identifier for the task.
            task: The coroutine to track.
            metadata: Optional metadata about the task.
        """
        ...

    async def get_status(self, task_id: str) -> dict[str, Any]:
        """Get the status of a registered task.

        Args:
            task_id: The task ID to query.

        Returns:
            Status dict with 'status', 'progress', 'result', 'error' fields.
        """
        ...

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task.

        Args:
            task_id: The task ID to cancel.

        Returns:
            True if task was cancelled, False if not found or already done.
        """
        ...

    async def list_tasks(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List registered tasks.

        Args:
            status: Filter by status (pending, running, done, cancelled).
            limit: Maximum number of tasks to return.

        Returns:
            List of task status dicts.
        """
        ...


__all__ = [
    "PipelineService",
    "TaskRegistryService",
]
