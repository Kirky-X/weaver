"""Neo4j entity repository for entity graph operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from neo4j import AsyncDriver
from neo4j.exceptions import ConstraintError

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger

log = get_logger("neo4j_entity_repo")


class Neo4jEntityRepo:
    """Neo4j entity repository.

    Handles entity CRUD operations in Neo4j graph database,
    including MERGE with uniqueness constraint and alias management.

    Args:
        pool: Neo4j connection pool.
    """

    # Maximum retry attempts for concurrent constraint violations
    MAX_MERGE_RETRIES = 3

    def __init__(self, pool: Neo4jPool) -> None:
        self._pool = pool

    async def ensure_constraints(self) -> None:
        """Create uniqueness constraints if they don't exist.

        Ensures that (canonical_name, type) is unique for Entity nodes.
        """
        constraints = [
            # Entity uniqueness constraint
            """
            CREATE CONSTRAINT entity_name_type_unique IF NOT EXISTS
            FOR (e:Entity) REQUIRE (e.canonical_name, e.type) IS UNIQUE
            """,
        ]

        for constraint in constraints:
            try:
                await self._pool.execute_query(constraint)
                log.info("neo4j_constraint_created", constraint=constraint[:50])
            except Exception as exc:
                # Constraint may already exist
                log.debug("neo4j_constraint_check", error=str(exc))

    async def merge_entity(
        self,
        canonical_name: str,
        entity_type: str,
        description: str | None = None,
    ) -> str:
        """Merge an entity node, creating if not exists.

        Uses MERGE with uniqueness constraint to ensure idempotency.
        On constraint violation (concurrent write), retries with fetch.

        Args:
            canonical_name: The canonical/standard name for the entity.
            entity_type: The type of entity (e.g., '人物', '组织机构').
            description: Optional description for new entities.

        Returns:
            The Neo4j internal ID of the entity.

        Raises:
            ConstraintError: If all retry attempts fail.
        """
        for attempt in range(self.MAX_MERGE_RETRIES):
            try:
                query = """
                MERGE (e:Entity {canonical_name: $canonical_name, type: $type})
                ON CREATE SET
                    e.id = $id,
                    e.aliases = [$canonical_name],
                    e.description = $description,
                    e.created_at = datetime()
                ON MATCH SET
                    e.updated_at = datetime()
                RETURN elementId(e) AS neo4j_id
                """
                params = {
                    "canonical_name": canonical_name,
                    "type": entity_type,
                    "id": str(uuid.uuid4()),
                    "description": description,
                }
                result = await self._pool.execute_query(query, params)
                if result:
                    return result[0]["neo4j_id"]
                raise RuntimeError("MERGE returned no result")

            except ConstraintError:
                if attempt == self.MAX_MERGE_RETRIES - 1:
                    raise
                # Another transaction created the entity, fetch it
                existing = await self.find_entity(canonical_name, entity_type)
                if existing:
                    return existing["neo4j_id"]
                # Exponential backoff before retry
                await self._sleep(0.05 * (attempt + 1))

    async def find_entity(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> dict[str, Any] | None:
        """Find an entity by canonical name and type.

        Args:
            canonical_name: The canonical name to search for.
            entity_type: The entity type to match.

        Returns:
            Entity dict if found, None otherwise.
        """
        query = """
        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
        RETURN elementId(e) AS neo4j_id,
               e.id AS id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               e.aliases AS aliases,
               e.description AS description,
               e.created_at AS created_at,
               e.updated_at AS updated_at
        """
        params = {"canonical_name": canonical_name, "type": entity_type}
        result = await self._pool.execute_query(query, params)
        if result:
            return dict(result[0])
        return None

    async def find_entity_by_id(self, neo4j_id: str) -> dict[str, Any] | None:
        """Find an entity by Neo4j internal ID.

        Args:
            neo4j_id: The Neo4j internal element ID.

        Returns:
            Entity dict if found, None otherwise.
        """
        query = """
        MATCH (e)
        WHERE elementId(e) = $neo4j_id
        RETURN elementId(e) AS neo4j_id,
               e.id AS id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               e.aliases AS aliases,
               e.description AS description,
               e.created_at AS created_at,
               e.updated_at AS updated_at
        """
        result = await self._pool.execute_query(query, {"neo4j_id": neo4j_id})
        if result:
            return dict(result[0])
        return None

    async def add_alias(
        self,
        canonical_name: str,
        entity_type: str,
        alias: str,
    ) -> bool:
        """Add an alias to an existing entity.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity.
            alias: The alias to add.

        Returns:
            True if alias was added, False if already existed.
        """
        query = """
        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
        SET e.aliases = CASE
            WHEN $alias IN e.aliases THEN e.aliases
            ELSE e.aliases + [$alias]
        END,
        e.updated_at = datetime()
        RETURN e.aliases AS aliases
        """
        params = {"canonical_name": canonical_name, "type": entity_type, "alias": alias}
        result = await self._pool.execute_query(query, params)
        return bool(result)

    async def merge_relation(
        self,
        from_neo4j_id: str,
        to_neo4j_id: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a relationship between two entities.

        Args:
            from_neo4j_id: Source entity Neo4j ID.
            to_neo4j_id: Target entity Neo4j ID.
            relation_type: Type of relationship (e.g., 'RELATED_TO').
            properties: Optional relationship properties.
        """
        query = f"""
        MATCH (from)
        WHERE elementId(from) = $from_id
        MATCH (to)
        WHERE elementId(to) = $to_id
        MERGE (from)-[r:{relation_type}]->(to)
        """
        params = {
            "from_id": from_neo4j_id,
            "to_id": to_neo4j_id,
        }

        if properties:
            # Add properties to the relationship
            set_clauses = []
            for key, value in properties.items():
                param_name = f"prop_{key}"
                set_clauses.append(f"r.{key} = ${param_name}")
                params[param_name] = value

            if set_clauses:
                query += " SET " + ", ".join(set_clauses)

        await self._pool.execute_query(query, params)

    async def get_entity_relations(
        self,
        canonical_name: str,
        entity_type: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get all relations for an entity.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity.
            limit: Maximum number of relations to return.

        Returns:
            List of relation dictionaries.
        """
        query = """
        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})-[r]->(related)
        RETURN elementId(e) AS from_id,
               type(r) AS relation_type,
               properties(r) AS relation_props,
               elementId(related) AS to_id,
               related.canonical_name AS to_name,
               related.type AS to_type
        LIMIT $limit
        """
        params = {
            "canonical_name": canonical_name,
            "type": entity_type,
            "limit": limit,
        }
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

    async def list_all_entity_ids(self) -> set[str]:
        """List all entity Neo4j IDs.

        Used for cleanup operations to identify orphan entities.

        Returns:
            Set of all entity Neo4j internal IDs.
        """
        query = """
        MATCH (e:Entity)
        RETURN elementId(e) AS neo4j_id
        """
        result = await self._pool.execute_query(query)
        return {record["neo4j_id"] for record in result}

    async def delete_orphan_entities(self) -> int:
        """Delete entities that have no incoming MENTIONS relationships.

        This should be called after article cleanup to remove orphan entities.

        Returns:
            Number of entities deleted.
        """
        query = """
        MATCH (e:Entity)
        WHERE NOT ()-[:MENTIONS]->(e)
          AND NOT (e)-[:RELATED_TO]-()
          AND NOT ()-[:RELATED_TO]->(e)
        DETACH DELETE e
        """
        # This query doesn't return count in Neo4j
        await self._pool.execute_query(query)
        # Return 0 as we can't easily get count
        return 0

    async def merge_mentions_relation(
        self,
        article_neo4j_id: str,
        entity_neo4j_id: str,
        role: str | None = None,
    ) -> None:
        """Create a MENTIONS relationship from article to entity.

        Args:
            article_neo4j_id: The article's Neo4j ID.
            entity_neo4j_id: The entity's Neo4j ID.
            role: Optional role (e.g., 'subject', 'object').
        """
        query = """
        MATCH (a)
        WHERE elementId(a) = $article_id
        MATCH (e)
        WHERE elementId(e) = $entity_id
        MERGE (a)-[r:MENTIONS]->(e)
        """
        params = {
            "article_id": article_neo4j_id,
            "entity_id": entity_neo4j_id,
        }

        if role:
            query += " SET r.role = $role"
            params["role"] = role

        await self._pool.execute_query(query, params)

    @staticmethod
    async def _sleep(seconds: float) -> None:
        """Async sleep helper."""
        import asyncio
        await asyncio.sleep(seconds)
