# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Dependency injection for migration API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import Depends

if TYPE_CHECKING:
    from container import Container


def get_container() -> Container:
    """Get the application container.

    This will be overridden by the actual dependency injection.
    """
    from api.endpoints._deps import get_container as _get_container

    return _get_container()


class MigrationService:
    """Service for managing migration operations."""

    def __init__(self, container: Container) -> None:
        """Initialize the migration service.

        Args:
            container: Application dependency container.
        """
        self._container = container
        self._tasks: dict[str, Any] = {}  # task_id -> engine
        self._results: dict[str, Any] = {}  # task_id -> result

    def create_task(self, config: Any) -> str:
        """Create a new migration task.

        Args:
            config: Migration configuration.

        Returns:
            Task ID.
        """
        import uuid

        task_id = str(uuid.uuid4())[:8]
        self._tasks[task_id] = {
            "config": config,
            "status": "pending",
            "engine": None,
            "created_at": datetime.utcnow(),
            "started_at": None,
        }
        return task_id

    async def run_migration(self, task_id: str) -> None:
        """Execute a migration task.

        Args:
            task_id: Task identifier.
        """
        from modules.migration.engine import MigrationEngine
        from modules.migration.mapping_registry import MappingRegistry

        task = self._tasks.get(task_id)
        if not task:
            return

        task["status"] = "running"
        task["started_at"] = datetime.utcnow()

        try:
            config = task["config"]

            # Create mapping registry if mapping file specified
            mapping_registry = None
            if config.mapping_file:
                mapping_registry = MappingRegistry()
                mapping_registry.load(config.mapping_file)

            # Create and run engine
            engine = MigrationEngine(
                config=config,
                container=self._container,
                mapping_registry=mapping_registry,
            )
            task["engine"] = engine

            result = await engine.run()
            self._results[task_id] = result
            task["status"] = "completed"

        except Exception as exc:
            task["status"] = "failed"
            task["error"] = str(exc)
            raise

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running migration task.

        Args:
            task_id: Task identifier.

        Returns:
            True if cancelled successfully.
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        engine = task.get("engine")
        if engine:
            engine.cancel()
            task["status"] = "cancelled"
            return True

        return False

    def get_status(self, task_id: str) -> dict[str, Any]:
        """Get task status.

        Args:
            task_id: Task identifier.

        Returns:
            Status dictionary.
        """
        task = self._tasks.get(task_id)
        if not task:
            return {"status": "not_found"}

        status = {
            "status": task["status"],
            "config": task["config"],
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
        }

        # Add progress if engine is running
        engine = task.get("engine")
        if engine:
            status["progress"] = engine.get_progress_dict()

        # Add result if completed
        result = self._results.get(task_id)
        if result:
            status["result"] = {
                "total_migrated": result.total_migrated,
                "total_expected": result.total_expected,
                "errors": result.errors,
            }

        return status


def get_migration_service(
    container: Container = Depends(get_container),
) -> MigrationService:
    """Get the migration service.

    Args:
        container: Application container.

    Returns:
        MigrationService instance.
    """
    return MigrationService(container)
