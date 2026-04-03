# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Neo4j entity repository for entity graph operations."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Any

from neo4j.exceptions import ConstraintError

from core.db.pool_protocols import GraphPool
from core.observability.logging import get_logger

log = get_logger("neo4j_entity_repo")

# Valid Neo4j relationship type: uppercase letters, underscores, and digits
# (must not start with a digit). Chinese characters are also allowed for
# backward compatibility with legacy data.
_EDGE_TYPE_RE = re.compile(r"^[A-Z_\u4e00-\u9fff][A-Z_\u4e00-\u9fff0-9]*$")


class Neo4jEntityRepo:
    """Neo4j entity repository.

    Handles entity CRUD operations in Neo4j graph database,
    including MERGE with uniqueness constraint and alias management.

    Supports both single and batch operations for efficiency.

    Args:
        pool: Graph database pool (Neo4j or LadybugDB).
    """

    MAX_MERGE_RETRIES = 3
    DEFAULT_BATCH_SIZE = 1000

    def __init__(self, pool: GraphPool) -> None:
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
        tier: int = 2,
    ) -> str:
        """Merge an entity node, creating if not exists.

        Uses MERGE with uniqueness constraint to ensure idempotency.
        On constraint violation (concurrent write), retries with fetch.

        If the entity already exists:
        - tier=1 (authoritative source) can update canonical_name
        - tier>1 (general source) only adds alias, keeps existing canonical_name

        Args:
            canonical_name: The canonical/standard name for the entity.
            entity_type: The type of entity (e.g., '人物', '组织机构').
            description: Optional description for new entities.
            tier: Source tier (1=authoritative, 2+=general). Lower = more authoritative.

        Returns:
            The Neo4j internal ID of the entity.

        Raises:
            ConstraintError: If all retry attempts fail.
        """
        for attempt in range(self.MAX_MERGE_RETRIES):
            try:
                existing = await self.find_entity(canonical_name, entity_type)

                if existing:
                    existing_tier = existing.get("tier", 2)
                    if tier < existing_tier:
                        query = """
                        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
                        SET e.canonical_name = $new_name,
                            e.tier = $tier,
                            e.updated_at = datetime()
                        RETURN elementId(e) AS neo4j_id
                        """
                        params = {
                            "canonical_name": canonical_name,
                            "type": entity_type,
                            "new_name": canonical_name,
                            "tier": tier,
                        }
                    else:
                        query = """
                        MATCH (e:Entity {canonical_name: $canonical_name, type: $type})
                        SET e.aliases = CASE
                            WHEN NOT $canonical_name IN e.aliases
                            THEN e.aliases + [$canonical_name]
                            ELSE e.aliases
                          END,
                            e.updated_at = datetime()
                        RETURN elementId(e) AS neo4j_id
                        """
                        params = {
                            "canonical_name": canonical_name,
                            "type": entity_type,
                        }
                else:
                    query = """
                    MERGE (e:Entity {canonical_name: $canonical_name, type: $type})
                    ON CREATE SET
                        e.id = $id,
                        e.aliases = [$canonical_name],
                        e.description = $description,
                        e.tier = $tier,
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
                        "tier": tier,
                    }

                result = await self._pool.execute_query(query, params)
                if result:
                    return result[0]["neo4j_id"]
                raise RuntimeError("MERGE returned no result")

            except ConstraintError:
                if attempt == self.MAX_MERGE_RETRIES - 1:
                    raise
                existing = await self.find_entity(canonical_name, entity_type)
                if existing:
                    return existing["neo4j_id"]
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
               e.tier AS tier,
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

    async def find_entities_by_ids(
        self,
        neo4j_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Find multiple entities by their Neo4j internal IDs in a single query.

        This is an optimized batch query to avoid N+1 patterns when looking up
        multiple entities by ID (e.g., after a vector similarity search).

        Args:
            neo4j_ids: List of Neo4j internal element IDs.

        Returns:
            List of entity dicts found (may be fewer than input if some IDs not found).
        """
        if not neo4j_ids:
            return []

        query = """
        UNWIND $ids AS id
        MATCH (e)
        WHERE elementId(e) = id
        RETURN elementId(e) AS neo4j_id,
               e.id AS id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               e.aliases AS aliases,
               e.description AS description,
               e.created_at AS created_at,
               e.updated_at AS updated_at
        """

        params = {"ids": neo4j_ids}
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

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
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create or update a typed relationship between two entities.

        The caller is responsible for normalising the edge type via
        ``RelationTypeNormalizer`` before calling this method.

        Args:
            from_neo4j_id: Source entity Neo4j element ID.
            to_neo4j_id: Target entity Neo4j element ID.
            edge_type: Normalised edge type name (e.g. ``PARTNERS_WITH``).
            properties: Optional relationship properties (``raw_type``,
                ``direction``, ``weight``, etc.).

        Raises:
            ValueError: If *edge_type* is not a valid Neo4j relationship type.
        """
        if not _EDGE_TYPE_RE.match(edge_type):
            raise ValueError(f"Invalid edge type: {edge_type}")

        query = f"""
        MATCH (from) WHERE elementId(from) = $from_id
        MATCH (to) WHERE elementId(to) = $to_id
        MERGE (from)-[r:{edge_type}]->(to)
        ON CREATE SET r.created_at = datetime(), r.updated_at = datetime(), r.weight = 1.0
        ON MATCH SET r.updated_at = datetime(), r.weight = r.weight + 0.1
        SET r += $props
        """
        params = {
            "from_id": from_neo4j_id,
            "to_id": to_neo4j_id,
            "props": properties or {},
        }

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
        """Delete entities that have no MENTIONS or RELATED_TO relationships.

        An orphan entity is defined as having:
        - No incoming MENTIONS relationship (no article mentions this entity)
        - No outgoing RELATED_TO relationship (entity doesn't relate to other entities)
        - No incoming RELATED_TO relationship (no entity relates to this entity)

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

    async def count_orphan_entities(self) -> int:
        """Count entities that have no MENTIONS or RELATED_TO relationships.

        An orphan entity is defined as having:
        - No incoming MENTIONS relationship (no article mentions this entity)
        - No outgoing RELATED_TO relationship (entity doesn't relate to other entities)
        - No incoming RELATED_TO relationship (no entity relates to this entity)

        Returns:
            Number of orphan entities.
        """
        query = """
        MATCH (e:Entity)
        WHERE NOT ()-[:MENTIONS]->(e)
          AND NOT (e)-[:RELATED_TO]-()
          AND NOT ()-[:RELATED_TO]->(e)
        RETURN count(e) AS orphan_count
        """
        result = await self._pool.execute_query(query)
        return result[0]["orphan_count"] if result else 0

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

    async def get_relation_types(
        self,
        canonical_name: str,
        entity_type: str,
    ) -> list[dict[str, Any]]:
        """Layer 1: Discover all relation types for an entity.

        Returns aggregated information about each distinct relationship type
        connected to the entity, excluding system types (MENTIONS, FOLLOWED_BY)
        and pruned entities.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity.

        Returns:
            List of dicts with ``relation_type``, ``target_count``, and
            ``primary_direction`` keys, ordered by ``target_count`` desc.
        """
        query = """
        MATCH (e:Entity {canonical_name: $name, type: $type})-[r]-(other:Entity)
        WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
          AND NOT other.pruned = true
        RETURN type(r) AS relation_type,
               count(DISTINCT other) AS target_count,
               head(collect(DISTINCT
                   CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END
               )) AS primary_direction
        ORDER BY target_count DESC
        """
        params = {"name": canonical_name, "type": entity_type}
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

    async def find_by_relation_types(
        self,
        canonical_name: str,
        entity_type: str,
        relation_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Layer 2: Search related entities by relation types.

        For symmetric relations an undirected pattern ``-[]-`` is used; for
        asymmetric relations a directed pattern ``-[]->`` is used.

        Args:
            canonical_name: The canonical name of the entity.
            entity_type: The type of the entity.
            relation_types: Optional list of relationship type names to filter.
                When *None* or empty all types are returned.
            limit: Maximum number of results.

        Returns:
            List of related-entity dicts with ``relation_type``,
            ``direction``, ``target_name``, ``target_type``,
            ``target_description`` and ``weight`` keys.
        """
        if not relation_types:
            query = """
            MATCH (e:Entity {canonical_name: $name, type: $type})-[r]-(other:Entity)
            WHERE type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
              AND NOT other.pruned = true
            RETURN type(r) AS relation_type,
                   CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                   other.canonical_name AS target_name,
                   other.type AS target_type,
                   other.description AS target_description,
                   coalesce(r.weight, 1.0) AS weight
            ORDER BY weight DESC
            LIMIT $limit
            """
            params = {"name": canonical_name, "type": entity_type, "limit": limit}
        else:
            # Validate all relation types
            for rt in relation_types:
                if not _EDGE_TYPE_RE.match(rt):
                    raise ValueError(f"Invalid relation type: {rt}")

            # Build dynamic query with type-specific patterns.
            # Each type matches as undirected so we capture both directions.
            type_filters = " OR ".join(f"type(r) = '{rt}'" for rt in relation_types)
            query = f"""
            MATCH (e:Entity {{canonical_name: $name, type: $type}})-[r]-(other:Entity)
            WHERE ({type_filters})
              AND type(r) <> 'MENTIONS' AND type(r) <> 'FOLLOWED_BY'
              AND NOT other.pruned = true
            RETURN type(r) AS relation_type,
                   CASE WHEN (e)-[r]->(other) THEN 'outgoing' ELSE 'incoming' END AS direction,
                   other.canonical_name AS target_name,
                   other.type AS target_type,
                   other.description AS target_description,
                   coalesce(r.weight, 1.0) AS weight
            ORDER BY weight DESC
            LIMIT $limit
            """
            params = {"name": canonical_name, "type": entity_type, "limit": limit}

        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

    @staticmethod
    async def _sleep(seconds: float) -> None:
        """Async sleep helper."""
        import asyncio

        await asyncio.sleep(seconds)

    async def merge_entities_batch(
        self,
        entities: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> dict[str, int]:
        """Merge multiple entities in batches using UNWIND.

        Args:
            entities: List of entity dicts with 'canonical_name', 'type', 'description'.
            batch_size: Batch size (default: DEFAULT_BATCH_SIZE).

        Returns:
            Dict with 'created' and 'updated' counts.
        """
        if not entities:
            return {"created": 0, "updated": 0}

        batch_size = batch_size or self.DEFAULT_BATCH_SIZE
        total_created = 0
        total_updated = 0

        for batch in self._chunk(entities, batch_size):
            query = """
            UNWIND $entities AS entity
            MERGE (e:Entity {canonical_name: entity.canonical_name, type: entity.type})
            ON CREATE SET
                e.id = entity.id,
                e.aliases = [entity.canonical_name],
                e.description = entity.description,
                e.created_at = datetime(),
                e.updated_at = datetime()
            ON MATCH SET
                e.updated_at = datetime(),
                e.description = CASE
                    WHEN e.description IS NULL AND entity.description IS NOT NULL
                    THEN entity.description
                    ELSE e.description
                END
            WITH e, CASE WHEN e.created_at = e.updated_at THEN 1 ELSE 0 END AS is_new
            RETURN sum(is_new) AS created, count(e) - sum(is_new) AS updated
            """

            params = {
                "entities": [
                    {
                        "canonical_name": e.get("canonical_name"),
                        "type": e.get("type"),
                        "id": str(uuid.uuid4()),
                        "description": e.get("description"),
                    }
                    for e in batch
                ]
            }

            result = await self._pool.execute_query(query, params)
            if result:
                total_created += result[0].get("created", 0)
                total_updated += result[0].get("updated", 0)

        return {"created": total_created, "updated": total_updated}

    async def add_aliases_batch(
        self,
        aliases: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Add aliases to multiple entities in batch.

        Args:
            aliases: List of dicts with 'canonical_name', 'type', 'alias'.
            batch_size: Batch size (default: DEFAULT_BATCH_SIZE).

        Returns:
            Number of entities updated.
        """
        if not aliases:
            return 0

        batch_size = batch_size or self.DEFAULT_BATCH_SIZE
        total_updated = 0

        for batch in self._chunk(aliases, batch_size):
            query = """
            UNWIND $aliases AS alias_data
            MATCH (e:Entity {canonical_name: alias_data.canonical_name, type: alias_data.type})
            SET e.aliases = CASE
                WHEN alias_data.alias IN e.aliases THEN e.aliases
                ELSE e.aliases + [alias_data.alias]
            END,
            e.updated_at = datetime()
            RETURN count(e) AS updated
            """

            params = {
                "aliases": [
                    {
                        "canonical_name": a.get("canonical_name"),
                        "type": a.get("type"),
                        "alias": a.get("alias"),
                    }
                    for a in batch
                ]
            }

            result = await self._pool.execute_query(query, params)
            if result:
                total_updated += result[0].get("updated", 0)

        return total_updated

    async def merge_relations_batch(
        self,
        relations: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Merge multiple relationships in batches grouped by edge type.

        Because Neo4j does not support parameterised relationship types inside
        ``UNWIND``, relations are grouped by *edge_type* and each group is
        executed as a separate batched query.

        Args:
            relations: List of dicts. Each dict must contain ``from_name``,
                ``from_type``, ``to_name``, ``to_type``, and optionally
                ``edge_type`` (defaults to ``RELATED_TO``) and ``properties``.
            batch_size: Batch size (default: ``DEFAULT_BATCH_SIZE * 2``).

        Returns:
            Total number of relationships created/updated.
        """
        if not relations:
            return 0

        batch_size = batch_size or (self.DEFAULT_BATCH_SIZE * 2)

        # Group by edge_type
        by_type: dict[str, list[dict[str, Any]]] = {}
        for r in relations:
            edge_type = r.get("edge_type", "RELATED_TO")
            by_type.setdefault(edge_type, []).append(r)

        total = 0
        for edge_type, group in by_type.items():
            if not _EDGE_TYPE_RE.match(edge_type):
                log.warning("merge_relations_batch_invalid_type", edge_type=edge_type)
                continue

            for chunk in self._chunk(group, batch_size):
                query = f"""
                UNWIND $relations AS rel
                MATCH (from:Entity {{canonical_name: rel.from_name, type: rel.from_type}})
                MATCH (to:Entity {{canonical_name: rel.to_name, type: rel.to_type}})
                MERGE (from)-[r:{edge_type}]->(to)
                ON CREATE SET r.created_at = datetime(), r.updated_at = datetime(), r.weight = 1.0
                ON MATCH SET r.updated_at = datetime(), r.weight = r.weight + 0.1
                SET r += rel.properties
                RETURN count(r) AS total
                """

                params = {
                    "relations": [
                        {
                            "from_name": r.get("from_name"),
                            "from_type": r.get("from_type"),
                            "to_name": r.get("to_name"),
                            "to_type": r.get("to_type"),
                            "properties": r.get("properties", {}),
                        }
                        for r in chunk
                    ]
                }

                result = await self._pool.execute_query(query, params)
                if result:
                    total += result[0].get("total", 0)

        return total

    async def merge_mentions_batch(
        self,
        mentions: list[dict[str, Any]],
        batch_size: int | None = None,
    ) -> int:
        """Merge multiple MENTIONS relationships in batches.

        Args:
            mentions: List of dicts with 'article_id', 'entity_name', 'entity_type', 'role'.
            batch_size: Batch size (default: DEFAULT_BATCH_SIZE * 5).

        Returns:
            Number of MENTIONS relationships created.
        """
        if not mentions:
            return 0

        batch_size = batch_size or (self.DEFAULT_BATCH_SIZE * 5)
        total_created = 0

        for batch in self._chunk(mentions, batch_size):
            query = """
            UNWIND $mentions AS m
            MATCH (a:Article {pg_id: m.article_id})
            MATCH (e:Entity {canonical_name: m.entity_name, type: m.entity_type})
            MERGE (a)-[r:MENTIONS]->(e)
            ON CREATE SET r.created_at = datetime()
            SET r.role = m.role
            RETURN count(r) AS total
            """

            params = {
                "mentions": [
                    {
                        "article_id": m.get("article_id"),
                        "entity_name": m.get("entity_name"),
                        "entity_type": m.get("entity_type"),
                        "role": m.get("role"),
                    }
                    for m in batch
                ]
            }

            result = await self._pool.execute_query(query, params)
            if result:
                total_created += result[0].get("total", 0)

        return total_created

    async def find_entities_batch(
        self,
        names: list[str],
        entity_type: str,
    ) -> list[dict[str, Any]]:
        """Find multiple entities by names in a single query.

        Args:
            names: List of canonical names to search for.
            entity_type: The entity type to match.

        Returns:
            List of entity dicts found.
        """
        if not names:
            return []

        query = """
        UNWIND $names AS name
        MATCH (e:Entity {canonical_name: name, type: $type})
        RETURN elementId(e) AS neo4j_id,
               e.id AS id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               e.aliases AS aliases,
               e.description AS description
        """

        params = {"names": names, "type": entity_type}
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

    async def find_entities_by_keys(
        self,
        keys: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Find multiple entities by (canonical_name, type) keys in a single query.

        This is an optimized batch query to avoid N+1 patterns when entities
        have different types. Each key dict must have 'canonical_name' and 'type'.

        Args:
            keys: List of dicts with 'canonical_name' and 'type' keys.

        Returns:
            List of entity dicts found (may be fewer than input if some not found).
        """
        if not keys:
            return []

        query = """
        UNWIND $keys AS key
        MATCH (e:Entity {canonical_name: key.canonical_name, type: key.type})
        RETURN elementId(e) AS neo4j_id,
               e.id AS id,
               e.canonical_name AS canonical_name,
               e.type AS type,
               e.aliases AS aliases,
               e.description AS description
        """

        params = {
            "keys": [
                {"canonical_name": k.get("canonical_name"), "type": k.get("type")} for k in keys
            ]
        }
        result = await self._pool.execute_query(query, params)
        return [dict(record) for record in result]

    async def delete_entities_batch(
        self,
        neo4j_ids: list[str],
        batch_size: int | None = None,
    ) -> int:
        """Delete multiple entities by their Neo4j IDs.

        Args:
            neo4j_ids: List of Neo4j internal element IDs.
            batch_size: Batch size (default: DEFAULT_BATCH_SIZE).

        Returns:
            Number of entities deleted.
        """
        if not neo4j_ids:
            return 0

        batch_size = batch_size or self.DEFAULT_BATCH_SIZE
        total_deleted = 0

        for batch in self._chunk(neo4j_ids, batch_size):
            query = """
            UNWIND $ids AS id
            MATCH (e)
            WHERE elementId(e) = id
            DETACH DELETE e
            RETURN count(e) AS deleted
            """
            result = await self._pool.execute_query(query, {"ids": batch})
            if result:
                total_deleted += result[0].get("deleted", 0)

        return total_deleted

    @staticmethod
    def _chunk(items: list[Any], size: int) -> Iterator[list[Any]]:
        """Split items into chunks of specified size."""
        for i in range(0, len(items), size):
            yield items[i : i + size]
