# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB entity repository for entity graph operations.

LadybugDB is a Kuzu fork with Cypher support. Key differences from Neo4j:
- No elementId() function - use id property as string
- No datetime() function - use timestamp integers
- Dynamic relationship types stored in RELATED_TO with edge_type property
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from core.observability.logging import get_logger

log = get_logger("ladybug_entity_repo")

# Valid edge type: uppercase letters, underscores, and digits
_EDGE_TYPE_RE = re.compile(r"^[A-Z_一-鿿][A-Z_一-鿿0-9]*$")


class LadybugEntityRepo:
    """LadybugDB entity repository.

    Handles entity CRUD operations in LadybugDB graph database.
    Uses id property instead of elementId(), and timestamp integers instead of datetime().

    Args:
        pool: LadybugPool instance.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def ensure_constraints(self) -> None:
        """Create node tables if they don't exist.

        In LadybugDB, schema is defined via CREATE NODE TABLE,
        which is handled by schema.py initialization.
        """
        pass  # Schema is initialized separately

    async def merge_entity(
        self,
        canonical_name: str,
        entity_type: str,
        description: str | None = None,
        tier: int = 2,
    ) -> str:
        """Merge an entity node, creating if not exists.

        Args:
            canonical_name: The canonical/standard name for the entity.
            entity_type: The type of entity.
            description: Optional description for new entities.
            tier: Source tier (1=authoritative, 2+=general).

        Returns:
            The entity ID.
        """
        now = int(time.time())
        entity_id = str(uuid.uuid4())

        # Check if exists
        existing = await self.find_entity(canonical_name, entity_type)
        if existing:
            # Update tier if more authoritative
            if tier < existing.get("tier", 2):
                query = """
                MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
                SET e.tier = $tier, e.updated_at = $updated_at
                RETURN e.id AS id
                """
                params = {
                    "canonical_name": canonical_name,
                    "type": entity_type,
                    "tier": tier,
                    "updated_at": now,
                }
            else:
                return existing["id"]
        else:
            # Create new entity
            query = """
            MERGE (e:Entity {canonical_name: $canonical_name, type: $type})
            ON CREATE SET
                e.id = $id,
                e.description = $description,
                e.tier = $tier,
                e.created_at = $created_at,
                e.updated_at = $updated_at
            RETURN e.id AS id
            """
            params = {
                "canonical_name": canonical_name,
                "type": entity_type,
                "id": entity_id,
                "description": description,
                "tier": tier,
                "created_at": now,
                "updated_at": now,
            }

        result = await self._pool.execute_query(query, params)
        if result:
            return result[0]["id"]
        return entity_id

    async def find_entity(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> dict[str, Any] | None:
        """Find an entity by canonical name and type."""
        query = """
        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
        RETURN e.id AS id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description,
               e.tier AS tier,
               e.created_at AS created_at,
               e.updated_at AS updated_at
        """
        result = await self._pool.execute_query(
            query, {"canonical_name": canonical_name, "type": entity_type}
        )
        if result:
            return dict(result[0])
        return None

    async def find_entity_by_id(self, entity_id: str) -> dict[str, Any] | None:
        """Find an entity by its ID."""
        query = """
        MATCH (e:Entity {id: $id})
        RETURN e.id AS id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               e.description AS description,
               e.tier AS tier,
               e.created_at AS created_at,
               e.updated_at AS updated_at
        """
        result = await self._pool.execute_query(query, {"id": entity_id})
        if result:
            return dict(result[0])
        return None

    async def find_entities_by_ids(
        self,
        entity_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Find multiple entities by their IDs."""
        if not entity_ids:
            return []

        results = []
        for eid in entity_ids:
            entity = await self.find_entity_by_id(eid)
            if entity:
                results.append(entity)
        return results

    async def add_alias(
        self,
        canonical_name: str,
        entity_type: str,
        alias: str,
    ) -> bool:
        """Add an alias to an existing entity.

        Note: LadybugDB doesn't support array types well, so we skip this.
        """
        # LadybugDB doesn't have good array support
        # This could be implemented with a separate Alias node if needed
        return True

    async def merge_relation(
        self,
        from_entity_id: str,
        to_entity_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a relationship between two entities.

        Uses RELATED_TO table with edge_type property for all relationships.
        """
        import json

        now = int(time.time())

        query = """
        MATCH (from:Entity {id: $from_id})
        MATCH (to:Entity {id: $to_id})
        MERGE (from)-[r:RELATED_TO {edge_type: $edge_type}]->(to)
        ON CREATE SET r.created_at = $created_at, r.updated_at = $updated_at
        ON MATCH SET r.updated_at = $updated_at
        SET r.properties = $properties
        """
        params = {
            "from_id": from_entity_id,
            "to_id": to_entity_id,
            "edge_type": edge_type,
            "properties": json.dumps(properties or {}),
            "created_at": now,
            "updated_at": now,
        }

        await self._pool.execute_query(query, params)

    async def get_entity_relations(
        self,
        canonical_name: str,
        entity_type: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get all relations for an entity."""
        query = """
        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})-[r:RELATED_TO]->(related)
        RETURN e.id AS from_id,
               r.edge_type AS relation_type,
               r.properties AS relation_props,
               related.id AS to_id,
               related.canonical_name AS to_name,
               related.type AS to_type
        LIMIT $limit
        """
        result = await self._pool.execute_query(
            query,
            {
                "canonical_name": canonical_name,
                "type": entity_type,
                "limit": limit,
            },
        )
        return [dict(record) for record in result]

    async def list_all_entity_ids(self) -> set[str]:
        """List all entity IDs."""
        query = """
        MATCH (e:Entity)
        RETURN e.id AS id
        """
        result = await self._pool.execute_query(query)
        return {record["id"] for record in result}

    async def delete_orphan_entities(self) -> int:
        """Delete entities that have no relationships."""
        # Find orphan entities
        query = """
        MATCH (e:Entity)
        WHERE NOT ()-[:MENTIONS]->(e) AND NOT (e)-[:RELATED_TO]->() AND NOT ()-[:RELATED_TO]->(e)
        RETURN e.id AS id
        """
        result = await self._pool.execute_query(query)
        orphan_ids = [r["id"] for r in result]

        # Delete each orphan
        for eid in orphan_ids:
            await self._pool.execute_query("MATCH (e:Entity {id: $id}) DELETE e", {"id": eid})

        return len(orphan_ids)

    async def count_orphan_entities(self) -> int:
        """Count orphan entities."""
        query = """
        MATCH (e:Entity)
        WHERE NOT ()-[:MENTIONS]->(e) AND NOT (e)-[:RELATED_TO]->() AND NOT ()-[:RELATED_TO]->(e)
        RETURN COUNT(e) AS count
        """
        result = await self._pool.execute_query(query)
        return result[0]["count"] if result else 0

    async def merge_mentions_relation(
        self,
        article_id: str,
        entity_id: str,
        role: str | None = None,
    ) -> None:
        """Create a MENTIONS relationship between article and entity."""
        query = """
        MATCH (a:Article {id: $article_id})
        MATCH (e:Entity {id: $entity_id})
        MERGE (a)-[r:MENTIONS]->(e)
        SET r.role = $role
        """
        await self._pool.execute_query(
            query, {"article_id": article_id, "entity_id": entity_id, "role": role}
        )

    async def get_relation_types(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> list[dict[str, Any]]:
        """Get all relation types for an entity."""
        query = """
        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})-[r:RELATED_TO]->()
        RETURN DISTINCT r.edge_type AS relation_type
        """
        result = await self._pool.execute_query(
            query, {"canonical_name": canonical_name, "type": entity_type}
        )
        return [dict(record) for record in result]

    async def find_by_relation_types(
        self,
        canonical_name: str,
        entity_type: str,
        relation_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find related entities by relation types."""
        if relation_types:
            # Query for specific relation types
            results = []
            for rt in relation_types:
                query = """
                MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
                      -[r:RELATED_TO {edge_type: $edge_type}]->(related)
                RETURN related.id AS id,
                       related.canonical_name AS canonical_name,
                       related.type AS type,
                       r.edge_type AS relation_type
                LIMIT $limit
                """
                result = await self._pool.execute_query(
                    query,
                    {
                        "canonical_name": canonical_name,
                        "type": entity_type,
                        "edge_type": rt,
                        "limit": limit,
                    },
                )
                results.extend([dict(r) for r in result])
            return results[:limit]
        else:
            # Query for all relations
            query = """
            MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
                  -[r:RELATED_TO]->(related)
            RETURN related.id AS id,
                   related.canonical_name AS canonical_name,
                   related.type AS type,
                   r.edge_type AS relation_type
            LIMIT $limit
            """
            result = await self._pool.execute_query(
                query,
                {
                    "canonical_name": canonical_name,
                    "type": entity_type,
                    "limit": limit,
                },
            )
            return [dict(r) for r in result]

    async def merge_entities_batch(
        self,
        entities: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> dict[str, int]:
        """Merge multiple entities."""
        created = 0
        updated = 0
        for entity in entities:
            existing = await self.find_entity(entity["canonical_name"], entity["entity_type"])
            if existing:
                updated += 1
            else:
                await self.merge_entity(
                    entity["canonical_name"],
                    entity["entity_type"],
                    entity.get("description"),
                    entity.get("tier", 2),
                )
                created += 1
        return {"created": created, "updated": updated}

    async def add_aliases_batch(
        self,
        aliases: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Add aliases to entities. Skipped in LadybugDB."""
        return len(aliases)

    async def merge_relations_batch(
        self,
        relations: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Merge multiple relations."""
        count = 0
        for rel in relations:
            await self.merge_relation(
                rel["from_id"],
                rel["to_id"],
                rel["edge_type"],
                rel.get("properties"),
            )
            count += 1
        return count

    async def merge_mentions_batch(
        self,
        mentions: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Merge multiple MENTIONS relationships."""
        count = 0
        for m in mentions:
            await self.merge_mentions_relation(
                m["article_id"],
                m["entity_id"],
                m.get("role"),
            )
            count += 1
        return count

    async def find_entities_batch(
        self,
        names: list[str],
        entity_type: str,
    ) -> list[dict[str, Any]]:
        """Find multiple entities by names."""
        results = []
        for name in names:
            entity = await self.find_entity(name, entity_type)
            if entity:
                results.append(entity)
        return results

    async def find_entities_by_keys(
        self,
        keys: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Find multiple entities by keys."""
        results = []
        for key in keys:
            entity = await self.find_entity(key["canonical_name"], key["type"])
            if entity:
                results.append(entity)
        return results

    async def delete_entities_batch(
        self,
        entity_ids: list[str],
        batch_size: int | None = None,
    ) -> int:
        """Delete multiple entities."""
        count = 0
        for eid in entity_ids:
            await self._pool.execute_query("MATCH (e:Entity {id: $id}) DELETE e", {"id": eid})
            count += 1
        return count
