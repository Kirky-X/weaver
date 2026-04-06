# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Data models for migration operations.

Defines configuration, schema, progress, and result dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ColumnDef:
    """Column definition for schema.

    Attributes:
        name: Column name.
        data_type: Database data type.
        nullable: Whether the column allows NULL values.
        default: Default value for the column.
    """

    name: str
    data_type: str
    nullable: bool = True
    default: Any = None


@dataclass(frozen=True)
class MigrationConfig:
    """Configuration for a migration operation.

    Attributes:
        source_db: Source database type ("postgres" | "duckdb" | "neo4j" | "ladybug").
        target_db: Target database type.
        tables: Tables/nodes to migrate (None = all).
        batch_size: Number of rows per batch.
        incremental_key: Column name for incremental migration.
        incremental_since: Starting value for incremental migration.
        mapping_file: Path to YAML mapping rules file.
        strict_mode: Whether to fail on type conversion errors.
    """

    source_db: str
    target_db: str
    tables: list[str] | None = None
    batch_size: int = 5000
    incremental_key: str | None = None
    incremental_since: Any = None
    mapping_file: str | None = None
    strict_mode: bool = False


@dataclass(frozen=True)
class MigrationSchema:
    """Schema definition for a relational table.

    Attributes:
        table: Table name.
        columns: List of column definitions.
        primary_key: Name of the primary key column.
        indexes: List of index names.
    """

    table: str
    columns: list[ColumnDef]
    primary_key: str
    indexes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NodeSchema:
    """Schema definition for a graph node label.

    Attributes:
        label: Node label name.
        primary_key: Property name used as primary key.
        properties: List of property definitions.
    """

    label: str
    primary_key: str
    properties: list[ColumnDef]


@dataclass(frozen=True)
class RelSchema:
    """Schema definition for a graph relationship type.

    Attributes:
        type: Relationship type name.
        source_label: Source node label.
        target_label: Target node label.
        properties: List of property definitions.
    """

    type: str
    source_label: str
    target_label: str
    properties: list[ColumnDef] = field(default_factory=list)


@dataclass
class MigrationProgress:
    """Progress tracking for a single table/node migration.

    Attributes:
        table: Table or node label name.
        total: Total number of items to migrate.
        migrated: Number of items already migrated.
        started_at: Migration start timestamp.
        status: Current status ("pending" | "running" | "completed" | "failed").
        error: Error message if failed.
    """

    table: str
    total: int
    migrated: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"
    error: str | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Calculate elapsed time in seconds."""
        return (datetime.utcnow() - self.started_at).total_seconds()

    @property
    def percent_complete(self) -> float:
        """Calculate completion percentage."""
        return (self.migrated / self.total * 100) if self.total > 0 else 0.0


@dataclass
class MigrationResult:
    """Final result of a migration operation.

    Attributes:
        config: Original migration configuration.
        items: Progress for each migrated item.
        started_at: Migration start timestamp.
        completed_at: Migration completion timestamp.
        status: Final status ("success" | "partial" | "failed").
        total_migrated: Total number of items migrated.
        total_expected: Total number of items expected.
        errors: List of error messages.
    """

    config: MigrationConfig
    items: list[MigrationProgress]
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "pending"
    total_migrated: int = 0
    total_expected: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        """Calculate total elapsed time in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return (datetime.utcnow() - self.started_at).total_seconds()

    @property
    def success(self) -> bool:
        """Check if migration was successful."""
        return self.status == "success"
