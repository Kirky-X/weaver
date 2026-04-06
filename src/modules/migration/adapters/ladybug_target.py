# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB target adapter for migration.

Implements GraphMigrationTarget protocol for writing data to LadybugDB.
"""

from __future__ import annotations

import json
from typing import Any

from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import NodeSchema, RelSchema


class LadybugTarget:
    """LadybugDB target adapter for migration.

    Implements: GraphMigrationTarget

    Writes data to a LadybugDB database during migration.
    """

    def __init__(self, pool: Any) -> None:
        """Initialize the LadybugDB target.

        Args:
            pool: LadybugPool instance with active connection.
        """
        self._pool = pool

    async def ensure_node_schema(self, schemas: list[NodeSchema]) -> None:
        """Ensure target node tables exist.

        LadybugDB uses a schema-flexible node table structure.

        Args:
            schemas: List of node schema definitions.
        """
        # LadybugDB creates tables on-demand
        # We can create indexes on frequently queried properties
        for schema in schemas:
            # Create index on primary key
            try:
                await self._pool.execute_query(f"""
                    CREATE INDEX IF NOT EXISTS idx_{schema.label.lower()}_{schema.primary_key.lower()}
                    ON nodes(label, properties->'{schema.primary_key}')
                """)
            except Exception:
                pass  # Index may already exist

    async def ensure_rel_schema(self, schemas: list[RelSchema]) -> None:
        """Ensure target relationship tables exist.

        Args:
            schemas: List of relationship schema definitions.
        """
        # LadybugDB creates edges table on-demand
        # Create indexes on relationship types
        for schema in schemas:
            try:
                await self._pool.execute_query(f"""
                    CREATE INDEX IF NOT EXISTS idx_edges_{schema.type.lower()}
                    ON edges(type)
                """)
            except Exception:
                pass

    async def write_nodes(self, label: str, nodes: list[dict[str, Any]]) -> int:
        """Write a batch of nodes.

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
            # Extract node ID
            node_id = node.get("id") or node.get("name") or node.get("_node_id")
            if not node_id:
                node_id = next(iter(node.values()), None) if node else None

            if not node_id:
                continue

            # Serialize properties (excluding metadata)
            props = {k: v for k, v in node.items() if not k.startswith("_")}
            props_json = json.dumps(props)

            # Use INSERT OR REPLACE for upsert
            query = """
                INSERT OR REPLACE INTO nodes (node_id, label, properties)
                VALUES (:node_id, :label, :properties)
            """

            try:
                await self._pool.execute_query(
                    query,
                    {
                        "node_id": str(node_id),
                        "label": label,
                        "properties": props_json,
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

            # Serialize properties (excluding metadata)
            props = {k: v for k, v in rel.items() if not k.startswith("_")}
            props_json = json.dumps(props) if props else "{}"

            # Generate edge ID
            edge_id = f"{source_id}_{rel_type}_{target_id}"

            query = """
                INSERT OR REPLACE INTO edges
                (edge_id, type, source_id, target_id, source_label, target_label, properties)
                VALUES (:edge_id, :type, :source_id, :target_id, :source_label, :target_label, :properties)
            """

            try:
                await self._pool.execute_query(
                    query,
                    {
                        "edge_id": edge_id,
                        "type": rel_type,
                        "source_id": str(source_id),
                        "target_id": str(target_id),
                        "source_label": source_label,
                        "target_label": target_label,
                        "properties": props_json,
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
            SELECT COUNT(*) AS count FROM nodes WHERE label = '{label}'
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
            SELECT COUNT(*) AS count FROM edges WHERE type = '{rel_type}'
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
            DELETE FROM nodes WHERE label = '{label}'
        """)
