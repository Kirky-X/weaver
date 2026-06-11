# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Neo4j target adapter for migration.

Implements GraphMigrationTarget protocol for writing data to Neo4j.
"""

from __future__ import annotations

from typing import Any

from core.observability import get_logger
from modules.migration.exceptions import ValidationFailedError
from modules.migration.models import NodeSchema, RelSchema

log = get_logger(__name__)


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
            except Exception as exc:
                # Constraint may already exist with different name
                log.debug("create_constraint_skipped", label=schema.label, error=str(exc))

            # Create index on primary key
            try:
                await self._pool.execute_query(f"""
                    CREATE INDEX IF NOT EXISTS FOR (n:`{schema.label}`)
                    ON (n.`{schema.primary_key}`)
                """)
            except Exception as exc:
                log.debug("create_index_skipped", label=schema.label, error=str(exc))

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
        """Write a batch of nodes using UNWIND MERGE.

        Args:
            label: Target node label.
            nodes: List of node property dictionaries.

        Returns:
            Number of nodes successfully written.
        """
        if not nodes:
            return 0

        # Build parameterized UNWIND query
        # Neo4j allows UNWIND but doesn't allow dynamic label, so we use f-string for label
        # (label comes from NodeSchema which is validated, not user input)
        query = f"""
        UNWIND $nodes AS node
        MERGE (n:{label} {{id: node.id}})
        SET n += node.props
        RETURN count(n) AS written
        """

        # Prepare nodes with id and props separated
        processed_nodes = []
        for node in nodes:
            node_id = node.get("id") or node.get("name") or node.get("_id")
            if not node_id:
                # Use first property value as id
                node_id = next(iter(node.values()), None) if node else None
            if not node_id:
                continue

            # Extract properties (exclude metadata keys starting with _)
            props = {k: v for k, v in node.items() if not k.startswith("_")}

            processed_nodes.append(
                {
                    "id": node_id,
                    "props": props,
                }
            )

        if not processed_nodes:
            return 0

        try:
            result = await self._pool.execute_query(query, {"nodes": processed_nodes})
            return (
                result[0].get("written", len(processed_nodes)) if result else len(processed_nodes)
            )
        except Exception as exc:
            log.warning("write_nodes_batch_failed", label=label, count=len(nodes), error=str(exc))
            return 0

    async def write_rels(self, rel_type: str, rels: list[dict[str, Any]]) -> int:
        """Write a batch of relationships using UNWIND MERGE.

        Groups relationships by source_label and target_label for batch processing.

        Args:
            rel_type: Target relationship type.
            rels: List of relationship dictionaries.

        Returns:
            Number of relationships successfully written.
        """
        if not rels:
            return 0

        # Group by source_label and target_label for efficient batching
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for rel in rels:
            source_id = rel.get("_source_id")
            target_id = rel.get("_target_id")
            if not source_id or not target_id:
                continue

            source_label = rel.get("_source_label", "Node")
            target_label = rel.get("_target_label", "Node")
            key = (source_label, target_label)

            props = {k: v for k, v in rel.items() if not k.startswith("_")}
            groups.setdefault(key, []).append(
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "props": props,
                }
            )

        total_written = 0
        for (source_label, target_label), group_rels in groups.items():
            # rel_type comes from RelSchema which is validated, not user input
            query = f"""
            UNWIND $rels AS rel
            MATCH (source:{source_label} {{id: rel.source_id}})
            MATCH (target:{target_label} {{id: rel.target_id}})
            MERGE (source)-[r:{rel_type}]->(target)
            SET r += rel.props
            RETURN count(r) AS written
            """

            try:
                result = await self._pool.execute_query(query, {"rels": group_rels})
                written = result[0].get("written", len(group_rels)) if result else len(group_rels)
                total_written += written
            except Exception as exc:
                log.warning(
                    "write_rels_batch_failed",
                    rel_type=rel_type,
                    source_label=source_label,
                    target_label=target_label,
                    count=len(group_rels),
                    error=str(exc),
                )

        return total_written

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
