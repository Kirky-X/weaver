# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Progress display for migration operations using Rich.

Provides real-time progress bars and summary tables for migration tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text


@dataclass
class TaskInfo:
    """Information about a migration task."""

    name: str
    total: int
    migrated: int = 0
    started_at: datetime | None = None
    completed: bool = False
    failed: bool = False
    error: str | None = None


class MigrationProgressDisplay:
    """Rich-based progress display for migration operations.

    Provides:
    - Real-time progress bars for each table/node
    - Transfer speed calculation
    - Elapsed and remaining time
    - Summary table on completion
    """

    def __init__(
        self,
        source_db: str,
        target_db: str,
        is_graph: bool = False,
        console: Console | None = None,
    ) -> None:
        """Initialize the progress display.

        Args:
            source_db: Source database name.
            target_db: Target database name.
            is_graph: Whether this is a graph migration.
            console: Rich console instance (optional).
        """
        self._console = console or Console()
        self._is_graph = is_graph
        self._source_db = source_db
        self._target_db = target_db

        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40, complete_style="green", finished_style="bold green"),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self._console,
        )

        self._tasks: dict[str, TaskID] = {}
        self._task_info: dict[str, TaskInfo] = {}
        self._started_at: datetime | None = None

    def _get_icon(self, name: str) -> str:
        """Get icon for a task based on its type."""
        if self._is_graph:
            if any(label in name for label in ("Entity", "Article", "Source", "Node")):
                return "●"
            return "○"
        return " "

    def start(self) -> None:
        """Start the progress display."""
        self._started_at = datetime.utcnow()
        self._progress.start()

    def stop(self) -> None:
        """Stop the progress display."""
        self._progress.stop()

    def add_table(self, name: str, total: int) -> None:
        """Add a new table/node to track.

        Args:
            name: Table or node label name.
            total: Total number of items to migrate.
        """
        if self._started_at is None:
            self.start()

        icon = self._get_icon(name)
        description = f"{icon} {name}"
        task_id = self._progress.add_task(description, total=total)
        self._tasks[name] = task_id
        self._task_info[name] = TaskInfo(
            name=name,
            total=total,
            started_at=datetime.utcnow(),
        )

    def update(self, name: str, advance: int = 1) -> None:
        """Update progress for a table/node.

        Args:
            name: Table or node label name.
            advance: Number of items completed.
        """
        if name in self._tasks:
            self._progress.update(self._tasks[name], advance=advance)
            self._task_info[name].migrated += advance

    def complete(self, name: str) -> None:
        """Mark a table/node as completed.

        Args:
            name: Table or node label name.
        """
        if name in self._tasks:
            icon = "✅"
            self._progress.update(self._tasks[name], description=f"{icon} {name}")
            self._task_info[name].completed = True

    def fail(self, name: str, error: str) -> None:
        """Mark a table/node as failed.

        Args:
            name: Table or node label name.
            error: Error message.
        """
        if name in self._tasks:
            icon = "❌"
            self._progress.update(self._tasks[name], description=f"{icon} {name}")
            self._task_info[name].failed = True
            self._task_info[name].error = error

    def cancel(self, name: str) -> None:
        """Mark a table/node as cancelled.

        Args:
            name: Table or node label name.
        """
        if name in self._tasks:
            icon = "⏹️"
            self._progress.update(self._tasks[name], description=f"{icon} {name}")

    def print_summary(self) -> None:
        """Print migration summary table."""
        self.stop()

        if not self._task_info:
            return

        # Build summary table
        table = Table(title="Migration Summary", show_header=True, header_style="bold")
        table.add_column("Table/Node", style="cyan")
        table.add_column("Total", justify="right")
        table.add_column("Migrated", justify="right")
        table.add_column("Status", justify="center")
        table.add_column("Time", justify="right")

        total_items = 0
        total_migrated = 0
        completed_count = 0
        failed_count = 0

        for info in self._task_info.values():
            total_items += info.total
            total_migrated += info.migrated

            if info.failed:
                status = "[red]Failed[/red]"
                failed_count += 1
            elif info.completed:
                status = "[green]Completed[/green]"
                completed_count += 1
            else:
                status = "[yellow]Partial[/yellow]"

            elapsed = ""
            if info.started_at:
                seconds = (datetime.utcnow() - info.started_at).total_seconds()
                elapsed = f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"

            table.add_row(
                info.name,
                str(info.total),
                str(info.migrated),
                status,
                elapsed,
            )

        # Print header
        db_type = "Graph" if self._is_graph else "Relational"
        header = Panel(
            Text.from_markup(
                f"[bold]{db_type} Migration[/bold]\n{self._source_db} → {self._target_db}"
            ),
            title="Weaver Data Migration",
            border_style="blue",
        )
        self._console.print(header)
        self._console.print()

        # Print table
        self._console.print(table)
        self._console.print()

        # Print totals
        totals = Table.grid(padding=(0, 2))
        totals.add_column(style="bold")
        totals.add_column(justify="right")
        totals.add_row("Total Items:", f"{total_migrated:,} / {total_items:,}")
        totals.add_row("Completed:", f"{completed_count} / {len(self._task_info)}")
        if failed_count:
            totals.add_row("Failed:", f"[red]{failed_count}[/red]")

        if self._started_at:
            elapsed = (datetime.utcnow() - self._started_at).total_seconds()
            totals.add_row("Total Time:", f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}")

        self._console.print(totals)

    def get_progress_dict(self) -> dict[str, dict[str, Any]]:
        """Get current progress as a dictionary.

        Returns:
            Dictionary mapping table names to their progress info.
        """
        result = {}
        for name, info in self._task_info.items():
            result[name] = {
                "total": info.total,
                "migrated": info.migrated,
                "completed": info.completed,
                "failed": info.failed,
                "error": info.error,
                "percent": (info.migrated / info.total * 100) if info.total > 0 else 0.0,
            }
        return result


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "1m 30s" or "45s".
    """
    if seconds < 60:
        return f"{int(seconds)}s"

    minutes = int(seconds // 60)
    secs = int(seconds % 60)

    if minutes < 60:
        return f"{minutes}m {secs}s"

    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m"
