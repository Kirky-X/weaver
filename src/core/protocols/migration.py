# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Migration protocol definitions for database data transfer.

This module defines Protocol classes for data migration between different
database systems. Using Protocol enables structural subtyping, allowing
any class that implements the required methods to satisfy the type.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MigrationSource(Protocol):
    """Protocol for relational data source adapters.

    Any class implementing these methods can be used as a MigrationSource
    for reading data from PostgreSQL or DuckDB.
    """

    async def read_schema(self) -> list[MigrationSchema]:
        """Read schema information for all tables.

        Returns:
            List of MigrationSchema objects describing each table.
        """
        ...

    async def read_batch(self, table: str, offset: int, limit: int) -> list[dict[str, Any]]:
        """Read a batch of rows from a table.

        Args:
            table: Table name to read from.
            offset: Row offset for pagination.
            limit: Maximum number of rows to read.

        Returns:
            List of row dictionaries.
        """
        ...

    async def read_incremental(
        self, table: str, key: str, since: Any, limit: int = 5000
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Read rows incrementally based on a key value.

        Uses keyset pagination for efficient large dataset handling.

        Args:
            table: Table name to read from.
            key: Column name to use for incremental filtering.
            since: Starting value for the key column.
            limit: Batch size for each iteration.

        Yields:
            Lists of row dictionaries.
        """
        ...

    async def count(self, table: str) -> int:
        """Count total rows in a table.

        Args:
            table: Table name to count.

        Returns:
            Total number of rows.
        """
        ...


@runtime_checkable
class MigrationTarget(Protocol):
    """Protocol for relational data target adapters.

    Any class implementing these methods can be used as a MigrationTarget
    for writing data to PostgreSQL or DuckDB.
    """

    async def ensure_schema(self, schema: MigrationSchema) -> None:
        """Ensure the target table exists with correct schema.

        Creates the table if it doesn't exist. May alter columns if needed.

        Args:
            schema: Schema definition for the table.
        """
        ...

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Write a batch of rows to a table.

        Args:
            table: Target table name.
            rows: List of row dictionaries to write.

        Returns:
            Number of rows successfully written.
        """
        ...

    async def verify(self, table: str, expected_count: int) -> bool:
        """Verify migration completed successfully.

        Args:
            table: Table name to verify.
            expected_count: Expected number of rows.

        Returns:
            True if verification passed.
        """
        ...


@runtime_checkable
class GraphMigrationSource(Protocol):
    """Protocol for graph database source adapters.

    Any class implementing these methods can be used as a GraphMigrationSource
    for reading data from Neo4j or LadybugDB.
    """

    async def read_node_schema(self) -> list[NodeSchema]:
        """Read schema information for all node labels.

        Returns:
            List of NodeSchema objects describing each node type.
        """
        ...

    async def read_rel_schema(self) -> list[RelSchema]:
        """Read schema information for all relationship types.

        Returns:
            List of RelSchema objects describing each relationship type.
        """
        ...

    async def read_nodes(self, label: str, offset: int, limit: int) -> list[dict[str, Any]]:
        """Read a batch of nodes by label.

        Args:
            label: Node label to read.
            offset: Row offset for pagination.
            limit: Maximum number of nodes to read.

        Returns:
            List of node property dictionaries.
        """
        ...

    async def read_rels(self, rel_type: str, offset: int, limit: int) -> list[dict[str, Any]]:
        """Read a batch of relationships by type.

        Args:
            rel_type: Relationship type to read.
            offset: Row offset for pagination.
            limit: Maximum number of relationships to read.

        Returns:
            List of relationship dictionaries including source/target info.
        """
        ...

    async def count_nodes(self, label: str) -> int:
        """Count total nodes with a given label.

        Args:
            label: Node label to count.

        Returns:
            Total number of nodes.
        """
        ...

    async def count_rels(self, rel_type: str) -> int:
        """Count total relationships of a given type.

        Args:
            rel_type: Relationship type to count.

        Returns:
            Total number of relationships.
        """
        ...


@runtime_checkable
class GraphMigrationTarget(Protocol):
    """Protocol for graph database target adapters.

    Any class implementing these methods can be used as a GraphMigrationTarget
    for writing data to Neo4j or LadybugDB.
    """

    async def ensure_node_schema(self, schemas: list[NodeSchema]) -> None:
        """Ensure target node tables exist with correct schema.

        Args:
            schemas: List of node schema definitions.
        """
        ...

    async def ensure_rel_schema(self, schemas: list[RelSchema]) -> None:
        """Ensure target relationship tables exist with correct schema.

        Args:
            schemas: List of relationship schema definitions.
        """
        ...

    async def write_nodes(self, label: str, nodes: list[dict[str, Any]]) -> int:
        """Write a batch of nodes.

        Args:
            label: Target node label.
            nodes: List of node property dictionaries.

        Returns:
            Number of nodes successfully written.
        """
        ...

    async def write_rels(self, rel_type: str, rels: list[dict[str, Any]]) -> int:
        """Write a batch of relationships.

        Args:
            rel_type: Target relationship type.
            rels: List of relationship dictionaries.

        Returns:
            Number of relationships successfully written.
        """
        ...

    async def verify_nodes(self, label: str, expected: int) -> bool:
        """Verify node migration completed successfully.

        Args:
            label: Node label to verify.
            expected: Expected number of nodes.

        Returns:
            True if verification passed.
        """
        ...

    async def verify_rels(self, rel_type: str, expected: int) -> bool:
        """Verify relationship migration completed successfully.

        Args:
            rel_type: Relationship type to verify.
            expected: Expected number of relationships.

        Returns:
            True if verification passed.
        """
        ...


# Schema data classes (forward references resolved via __future__ annotations)
# These are imported from models.py but defined here for Protocol completeness

# Note: The actual dataclass definitions are in modules/migration/models.py
# This file only defines the Protocol interfaces


# Type aliases for Protocol return types (actual implementations in models.py)
# These are placeholder types for Protocol signatures
class MigrationSchema(Protocol):
    """Protocol for table schema information."""

    table: str
    columns: list[Any]  # ColumnDef
    primary_key: str
    indexes: list[str]


class NodeSchema(Protocol):
    """Protocol for node schema information."""

    label: str
    primary_key: str
    properties: list[Any]  # ColumnDef


class RelSchema(Protocol):
    """Protocol for relationship schema information."""

    type: str
    source_label: str
    target_label: str
    properties: list[Any]  # ColumnDef
