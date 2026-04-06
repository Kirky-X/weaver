# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Neo4j source adapter for migration.

Implements GraphMigrationSource protocol for reading data from Neo4j.
"""

from __future__ import annotations

from typing import Any

from core.db.safe_query import validate_edge_type, validate_neo4j_label
from modules.migration.models import ColumnDef, NodeSchema, RelSchema


class Neo4jSource:
    """Neo4j source adapter for migration.

    Implements: GraphMigrationSource

    Reads schema and data from a Neo4j database for migration
    to LadybugDB or other target databases.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the Neo4j source.

        Args:
            pool: Neo4jPool instance with active connection.
        """
        self._pool = pool

    async def read_node_schema(self) -> list[NodeSchema]:
        """Read schema information for all node labels.

        Returns:
            List of NodeSchema objects describing each node type.
        """
        schemas = []

        # Get all labels
        labels_result = await self._pool.execute_query("""
            CALL db.labels() YIELD label
            RETURN label
            ORDER BY label
        """)

        for label_row in labels_result:
            label = label_row["label"]

            # Validate label before use
            try:
                validate_neo4j_label(label)
            except ValueError:
                continue

            # Get properties for this label using parameterized query
            props_result = await self._pool.execute_query(
                """
                MATCH (n)
                WHERE $label IN labels(n)
                WITH n, keys(n) AS props
                UNWIND props AS prop
                WITH DISTINCT prop
                RETURN prop
                ORDER BY prop
                """,
                {"label": label},
            )

            properties = []
            for prop_row in props_result:
                prop_name = prop_row["prop"]
                properties.append(
                    ColumnDef(
                        name=prop_name,
                        data_type="String",  # Neo4j is dynamically typed
                        nullable=True,
                    )
                )

            # Determine primary key (look for 'id', 'name', or use first property)
            primary_key = "id"
            for prop in properties:
                if prop.name.lower() == "id":
                    primary_key = prop.name
                    break
                elif prop.name.lower() == "name":
                    primary_key = prop.name

            if not properties:
                properties.append(ColumnDef(name="id", data_type="String", nullable=False))

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

        # Get all relationship types
        types_result = await self._pool.execute_query("""
            CALL db.relationshipTypes() YIELD relationshipType
            RETURN relationshipType
            ORDER BY relationshipType
        """)

        for type_row in types_result:
            rel_type = type_row["relationshipType"]

            # Validate rel_type before use
            try:
                validate_edge_type(rel_type)
            except ValueError:
                continue

            # Get source/target labels and properties for this relationship type (parameterized)
            sample_result = await self._pool.execute_query(
                """
                MATCH (source)-[r]->(target)
                WHERE type(r) = $relType
                WITH source, target, keys(r) AS props
                LIMIT 1
                RETURN
                    labels(source)[0] AS source_label,
                    labels(target)[0] AS target_label,
                    props
                """,
                {"relType": rel_type},
            )

            if sample_result:
                sample = sample_result[0]
                source_label = sample.get("source_label", "Node")
                target_label = sample.get("target_label", "Node")
                props = sample.get("props", [])

                properties = [
                    ColumnDef(name=prop, data_type="String", nullable=True) for prop in props
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
        validate_neo4j_label(label)
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")
        if limit <= 0:
            raise ValueError(f"limit must be positive, got {limit}")

        result = await self._pool.execute_query(
            """
            MATCH (n)
            WHERE $label IN labels(n)
            RETURN n
            SKIP $offset
            LIMIT $limit
            """,
            {"label": label, "offset": offset, "limit": limit},
        )

        nodes = []
        for row in result:
            node = row.get("n", {})
            nodes.append(dict(node))

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
        validate_edge_type(rel_type)
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")
        if limit <= 0:
            raise ValueError(f"limit must be positive, got {limit}")

        result = await self._pool.execute_query(
            """
            MATCH (source)-[r]->(target)
            WHERE type(r) = $relType
            RETURN
                elementId(source) AS source_id,
                elementId(target) AS target_id,
                labels(source)[0] AS source_label,
                labels(target)[0] AS target_label,
                r
            SKIP $offset
            LIMIT $limit
            """,
            {"relType": rel_type, "offset": offset, "limit": limit},
        )

        rels = []
        for row in result:
            rel_data = dict(row.get("r", {}))
            rel_data["_source_id"] = row.get("source_id")
            rel_data["_target_id"] = row.get("target_id")
            rel_data["_source_label"] = row.get("source_label")
            rel_data["_target_label"] = row.get("target_label")
            rels.append(rel_data)

        return rels

    async def count_nodes(self, label: str) -> int:
        """Count total nodes with a given label.

        Args:
            label: Node label to count.

        Returns:
            Total number of nodes.
        """
        validate_neo4j_label(label)

        result = await self._pool.execute_query(
            """
            MATCH (n)
            WHERE $label IN labels(n)
            RETURN COUNT(n) AS count
            """,
            {"label": label},
        )

        return result[0].get("count", 0) if result else 0

    async def count_rels(self, rel_type: str) -> int:
        """Count total relationships of a given type.

        Args:
            rel_type: Relationship type to count.

        Returns:
            Total number of relationships.
        """
        validate_edge_type(rel_type)

        result = await self._pool.execute_query(
            """
            MATCH ()-[r]->()
            WHERE type(r) = $relType
            RETURN COUNT(r) AS count
            """,
            {"relType": rel_type},
        )

        return result[0].get("count", 0) if result else 0

    async def get_label_names(self) -> list[str]:
        """Get list of all node label names."""
        result = await self._pool.execute_query("""
            CALL db.labels() YIELD label
            RETURN label
            ORDER BY label
        """)
        return [row["label"] for row in result]

    async def get_rel_type_names(self) -> list[str]:
        """Get list of all relationship type names."""
        result = await self._pool.execute_query("""
            CALL db.relationshipTypes() YIELD relationshipType
            RETURN relationshipType
            ORDER BY relationshipType
        """)
        return [row["relationshipType"] for row in result]
