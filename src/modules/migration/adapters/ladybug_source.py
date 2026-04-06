# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB source adapter for migration.

Implements GraphMigrationSource protocol for reading data from LadybugDB.
"""

from __future__ import annotations

import json
from typing import Any

from core.db.safe_query import validate_sql_identifier
from modules.migration.models import ColumnDef, NodeSchema, RelSchema


class LadybugSource:
    """LadybugDB source adapter for migration.

    Implements: GraphMigrationSource

    Reads schema and data from a LadybugDB database for migration
    to Neo4j or other target databases.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the LadybugDB source.

        Args:
            pool: LadybugPool instance with active connection.
        """
        self._pool = pool

    async def read_node_schema(self) -> list[NodeSchema]:
        """Read schema information for all node labels.

        Returns:
            List of NodeSchema objects describing each node type.
        """
        schemas = []

        # LadybugDB stores node labels in a system table
        # Query existing nodes to get distinct labels
        result = await self._pool.execute_query("""
            SELECT DISTINCT label FROM nodes ORDER BY label
        """)

        for row in result:
            label = row.get("label")
            if not label:
                continue

            # Validate label before use
            try:
                validate_sql_identifier(label, "label")
            except ValueError:
                continue

            # Get properties for this label by sampling a node (parameterized)
            sample_result = await self._pool.execute_query(
                """
                SELECT properties FROM nodes
                WHERE label = $1
                LIMIT 1
                """,
                {"1": label},  # DuckDB uses positional params as keys
            )

            properties = []
            primary_key = "id"

            if sample_result:
                props = sample_result[0].get("properties", {})
                if isinstance(props, str):
                    try:
                        props = json.loads(props)
                    except json.JSONDecodeError:
                        props = {}

                for prop_name in props:
                    if prop_name.lower() == "id" or (
                        prop_name.lower() == "name" and primary_key == "id"
                    ):
                        primary_key = prop_name

                    properties.append(
                        ColumnDef(
                            name=prop_name,
                            data_type="STRING",
                            nullable=True,
                        )
                    )

            if not properties:
                properties.append(ColumnDef(name="id", data_type="STRING", nullable=False))

            schemas.append(
                NodeSchema(
                    label=label,
                    primary_key=primary_key,
                    properties=properties,
                )
            )

        return schemas

    async def read_rel_schema(self) -> list[RelSchema]:
        """Read schema information for all relationship types.

        Returns:
            List of RelSchema objects describing each relationship type.
        """
        schemas = []

        # Get distinct relationship types
        result = await self._pool.execute_query("""
            SELECT DISTINCT type FROM edges ORDER BY type
        """)

        for row in result:
            rel_type = row.get("type")
            if not rel_type:
                continue

            # Validate rel_type before use
            try:
                validate_sql_identifier(rel_type, "rel_type")
            except ValueError:
                continue

            # Sample a relationship to get source/target labels (parameterized)
            sample_result = await self._pool.execute_query(
                """
                SELECT source_label, target_label, properties FROM edges
                WHERE type = $1
                LIMIT 1
                """,
                {"1": rel_type},
            )

            if sample_result:
                sample = sample_result[0]
                source_label = sample.get("source_label", "Node")
                target_label = sample.get("target_label", "Node")
                props = sample.get("properties", {})

                if isinstance(props, str):
                    try:
                        props = json.loads(props)
                    except json.JSONDecodeError:
                        props = {}

                properties = [
                    ColumnDef(name=prop, data_type="STRING", nullable=True) for prop in props
                ]

                schemas.append(
                    RelSchema(
                        type=rel_type,
                        source_label=source_label,
                        target_label=target_label,
                        properties=properties,
                    )
                )

        return schemas

    async def read_nodes(
        self,
        label: str,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read a batch of nodes by label.

        Args:
            label: Node label to read.
            offset: Row offset for pagination.
            limit: Maximum number of nodes to read.

        Returns:
            List of node property dictionaries.
        """
        # Validate inputs
        validate_sql_identifier(label, "label")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")
        if limit <= 0:
            raise ValueError(f"limit must be positive, got {limit}")

        result = await self._pool.execute_query(
            """
            SELECT node_id, properties FROM nodes
            WHERE label = $1
            ORDER BY node_id
            OFFSET $2
            LIMIT $3
            """,
            {"1": label, "2": offset, "3": limit},
        )

        nodes = []
        for row in result:
            props = row.get("properties", {})
            if isinstance(props, str):
                try:
                    props = json.loads(props)
                except json.JSONDecodeError:
                    props = {}

            props["_node_id"] = row.get("node_id")
            nodes.append(props)

        return nodes

    async def read_rels(
        self,
        rel_type: str,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read a batch of relationships by type.

        Args:
            rel_type: Relationship type to read.
            offset: Row offset for pagination.
            limit: Maximum number of relationships to read.

        Returns:
            List of relationship dictionaries including source/target info.
        """
        # Validate inputs
        validate_sql_identifier(rel_type, "rel_type")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")
        if limit <= 0:
            raise ValueError(f"limit must be positive, got {limit}")

        result = await self._pool.execute_query(
            """
            SELECT edge_id, source_id, target_id, source_label, target_label, properties
            FROM edges
            WHERE type = $1
            ORDER BY edge_id
            OFFSET $2
            LIMIT $3
            """,
            {"1": rel_type, "2": offset, "3": limit},
        )

        rels = []
        for row in result:
            props = row.get("properties", {})
            if isinstance(props, str):
                try:
                    props = json.loads(props)
                except json.JSONDecodeError:
                    props = {}

            props["_source_id"] = row.get("source_id")
            props["_target_id"] = row.get("target_id")
            props["_source_label"] = row.get("source_label")
            props["_target_label"] = row.get("target_label")
            rels.append(props)

        return rels

    async def count_nodes(self, label: str) -> int:
        """Count total nodes with a given label.

        Args:
            label: Node label to count.

        Returns:
            Total number of nodes.
        """
        validate_sql_identifier(label, "label")

        result = await self._pool.execute_query(
            """
            SELECT COUNT(*) AS count FROM nodes WHERE label = $1
            """,
            {"1": label},
        )

        return result[0].get("count", 0) if result else 0

    async def count_rels(self, rel_type: str) -> int:
        """Count total relationships of a given type.

        Args:
            rel_type: Relationship type to count.

        Returns:
            Total number of relationships.
        """
        validate_sql_identifier(rel_type, "rel_type")

        result = await self._pool.execute_query(
            """
            SELECT COUNT(*) AS count FROM edges WHERE type = $1
            """,
            {"1": rel_type},
        )

        return result[0].get("count", 0) if result else 0

    async def get_label_names(self) -> list[str]:
        """Get list of all node label names."""
        result = await self._pool.execute_query("""
            SELECT DISTINCT label FROM nodes ORDER BY label
        """)
        return [row["label"] for row in result]

    async def get_rel_type_names(self) -> list[str]:
        """Get list of all relationship type names."""
        result = await self._pool.execute_query("""
            SELECT DISTINCT type FROM edges ORDER BY type
        """)
        return [row["type"] for row in result]
