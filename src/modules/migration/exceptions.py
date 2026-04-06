# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Exception classes for migration operations."""

from __future__ import annotations

from typing import Any


class MigrationError(Exception):
    """Base exception for migration errors.

    Attributes:
        message: Error message.
        table: Related table name (if applicable).
        cause: Original exception that caused this error.
    """

    def __init__(
        self,
        message: str,
        table: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.table = table
        self.cause = cause
        super().__init__(message)

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.table:
            parts.append(f" (table: {self.table})")
        if self.cause:
            parts.append(f" caused by: {self.cause}")
        return "".join(parts)


class SchemaMismatchError(MigrationError):
    """Raised when source and target schemas are incompatible."""

    def __init__(
        self,
        source_table: str,
        target_table: str,
        details: str,
    ) -> None:
        message = f"Schema mismatch between {source_table} and {target_table}: {details}"
        super().__init__(message, table=source_table)


class TypeConversionError(MigrationError):
    """Raised when a value cannot be converted between types.

    Attributes:
        column: Column name where conversion failed.
        value: The value that couldn't be converted.
        source_type: Source database type.
        target_type: Target database type.
    """

    def __init__(
        self,
        column: str,
        value: Any,
        source_type: str,
        target_type: str,
        table: str | None = None,
    ) -> None:
        self.column = column
        self.value = value
        self.source_type = source_type
        self.target_type = target_type
        message = f"Cannot convert {column}: {value!r} ({source_type} -> {target_type})"
        super().__init__(message, table=table)


class ConnectionError(MigrationError):
    """Raised when database connection fails."""

    def __init__(
        self,
        database: str,
        operation: str,
        cause: Exception | None = None,
    ) -> None:
        message = f"Connection failed to {database} during {operation}"
        super().__init__(message, cause=cause)


class IntegrityError(MigrationError):
    """Raised when data integrity constraint is violated."""

    def __init__(
        self,
        table: str,
        constraint: str,
        details: str,
    ) -> None:
        message = f"Integrity constraint violation on {table}.{constraint}: {details}"
        super().__init__(message, table=table)


class BatchFailedError(MigrationError):
    """Raised when a batch operation fails.

    Attributes:
        batch_offset: Starting offset of the failed batch.
        succeeded: Number of items that succeeded before failure.
        failed: Number of items that failed.
    """

    def __init__(
        self,
        table: str,
        batch_offset: int,
        succeeded: int,
        failed: int,
        cause: Exception | None = None,
    ) -> None:
        self.batch_offset = batch_offset
        self.succeeded = succeeded
        self.failed = failed
        message = f"Batch failed on {table} at offset {batch_offset}: {succeeded} succeeded, {failed} failed"
        super().__init__(message, table=table, cause=cause)


class ValidationFailedError(MigrationError):
    """Raised when post-migration validation fails."""

    def __init__(
        self,
        table: str,
        expected: int,
        actual: int,
    ) -> None:
        message = f"Validation failed for {table}: expected {expected} rows, got {actual}"
        super().__init__(message, table=table)


class UnsupportedDatabaseError(MigrationError):
    """Raised when an unsupported database type is specified."""

    def __init__(self, database: str, supported: list[str]) -> None:
        message = f"Unsupported database: {database}. Supported: {', '.join(supported)}"
        super().__init__(message)
