# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Neo4j target adapter for migration.

Implements GraphMigrationTarget protocol for writing data to Neo4j.
"""

from __future__ import annotations

from typing import Any

from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import NodeSchema, RelSchema


class Neo4jTarget:
    """Neo4j target adapter for migration.

    Implements: GraphMigrationTarget

    Writes data to a Neo4j database during migration.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the Neo4j target.

        Args:
            pool: Neo4jPool instance with active connection.
        """
        self._pool = pool

    async def ensure_node_schema(self, schemas: list[NodeSchema]) -> None:
        """Ensure target node labels exist with constraints.

        Creates indexes and unique constraints for primary keys.

        Args:
            schemas: List of node schema definitions.
        """
        for schema in schemas:
            # Create unique constraint on primary key
            try:
                await self._pool.execute_query(f"""
                    CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{schema.label}`)
                    REQUIRE n.`{schema.primary_key}` IS UNIQUE
                """)
            except Exception:
                # Constraint may already exist with different name
                pass

            # Create index on primary key
            try:
                await self._pool.execute_query(f"""
                    CREATE INDEX IF NOT EXISTS FOR (n:`{schema.label}`)
                    ON (n.`{schema.primary_key}`)
                """)
            except Exception:
                pass

    async def ensure_rel_schema(self, schemas: list[RelSchema]) -> None:
        """Ensure target relationship types can be created.

        Neo4j doesn't require relationship schema pre-creation,
        but we can create indexes on relationship properties if needed.

        Args:
            schemas: List of relationship schema definitions.
        """
        # Neo4j creates relationships on-demand, no schema setup needed
        pass

    async def write_nodes(self, label: str, nodes: list[dict[str, Any]]) -> int:
        """Write a batch of nodes.

        Uses MERGE for upsert behavior based on id property.

        Args:
            label: Target node label.
            nodes: List of node property dictionaries.

        Returns:
            Number of nodes successfully written.
        """
        if not nodes:
            return 0

        written = 0

        for node in nodes:
            # Find the id property
            node_id = node.get("id") or node.get("name") or node.get("_id")
            if not node_id:
                # Use first property value as id
                node_id = next(iter(node.values()), None) if node else None

            if not node_id:
                continue

            # Build property assignments
            props_list = []
            for key, value in node.items():
                if key.startswith("_"):
                    continue
                props_list.append(f"n.`{key}` = ${key}")

            props_set = ", ".join(props_list) if props_list else ""

            # Use MERGE for upsert
            query = f"""
                MERGE (n:`{label}` {{id: $node_id}})
                SET n += $props
            """

            # Alternative: use name as key if id doesn't exist
            if "id" not in node and "name" in node:
                query = f"""
                    MERGE (n:`{label}` {{name: $node_id}})
                    SET n += $props
                """

            try:
                await self._pool.execute_query(
                    query,
                    {
                        "node_id": node_id,
                        "props": node,
                    },
                )
                written += 1
            except Exception:
                pass

        return written

    async def write_rels(self, rel_type: str, rels: list[dict[str, Any]]) -> int:
        """Write a batch of relationships.

        Args:
            rel_type: Target relationship type.
            rels: List of relationship dictionaries.

        Returns:
            Number of relationships successfully written.
        """
        if not rels:
            return 0

        written = 0

        for rel in rels:
            source_id = rel.get("_source_id")
            target_id = rel.get("_target_id")
            source_label = rel.get("_source_label", "Node")
            target_label = rel.get("_target_label", "Node")

            if not source_id or not target_id:
                continue

            # Extract relationship properties (exclude metadata)
            props = {k: v for k, v in rel.items() if not k.startswith("_")}

            # Build property assignments
            props_set = ""
            if props:
                props_parts = [f"r.`{k}` = ${k}" for k in props]
                props_set = f"SET {', '.join(props_parts)}"

            query = f"""
                MATCH (source:`{source_label}` {{id: $source_id}})
                MATCH (target:`{target_label}` {{id: $target_id}})
                MERGE (source)-[r:`{rel_type}`]->(target)
                {props_set}
            """

            try:
                await self._pool.execute_query(
                    query,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        **props,
                    },
                )
                written += 1
            except Exception:
                pass

        return written

    async def verify_nodes(self, label: str, expected: int) -> bool:
        """Verify node migration completed successfully.

        Args:
            label: Node label to verify.
            expected: Expected number of nodes.

        Returns:
            True if verification passed.
        """
        result = await self._pool.execute_query(f"""
            MATCH (n:`{label}`)
            RETURN COUNT(n) AS count
        """)

        actual = result[0].get("count", 0) if result else 0

        if actual < expected:
            raise ValidationFailedError(
                table=label,
                expected=expected,
                actual=actual,
            )

        return True

    async def verify_rels(self, rel_type: str, expected: int) -> bool:
        """Verify relationship migration completed successfully.

        Args:
            rel_type: Relationship type to verify.
            expected: Expected number of relationships.

        Returns:
            True if verification passed.
        """
        result = await self._pool.execute_query(f"""
            MATCH ()-[r:`{rel_type}`]->()
            RETURN COUNT(r) AS count
        """)

        actual = result[0].get("count", 0) if result else 0

        if actual < expected:
            raise ValidationFailedError(
                table=rel_type,
                expected=expected,
                actual=actual,
            )

        return True

    async def clear_label(self, label: str) -> None:
        """Delete all nodes with a given label."""
        await self._pool.execute_query(f"""
            MATCH (n:`{label}`)
            DETACH DELETE n
        """)
