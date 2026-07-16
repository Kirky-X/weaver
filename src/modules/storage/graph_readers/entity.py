# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Entity reader for graph repository.

Handles entity-centric read operations: single entity lookup, entity
relations, co-mentioned entities, relation type summaries, and
relation-type-filtered entity discovery with co-occurrence weighting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from core.utils.time_utils import convert_timestamp
from modules.storage.graph_readers.base import GraphReaderBase

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class GraphEntityReader(GraphReaderBase):
    """Reader for entity-centric graph operations.

    Provides read access to entities and their relationships, including
    relation-type summaries and co-occurrence-weighted entity discovery.
    Query execution with fallback is delegated to the injected
    ``execute_fn`` callable.

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        execute_fn: Callable that runs a query with fallback support.
    """

    async def get_entity(self, canonical_name: str) -> dict[str, Any] | None:
        """Get entity by canonical name.

        Args:
            canonical_name: Entity canonical name.

        Returns:
            Entity dict or None if not found.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_entity_query(),
            {"name": canonical_name},
        )
        if result:
            record = result[0]
            updated_at = convert_timestamp(record.get("updated_at"))

            return {
                "id": record.get("id") or "",
                "canonical_name": record.get("canonical_name") or "",
                "type": record.get("type") or "未知",
                "aliases": record.get("aliases"),
                "description": record.get("description"),
                "updated_at": updated_at,
            }
        return None

    async def get_entity_relations(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get relationships from an entity.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of relationships.

        Returns:
            List of relationship dicts.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_entity_relations_query(),
            {"name": canonical_name, "limit": limit},
        )
        relations = []
        for row in result:
            created_at = convert_timestamp(row.get("created_at"))
            relations.append(
                {
                    "target": row["target"],
                    "relation_type": row["relation_type"] or "RELATED_TO",
                    "source_article_id": row.get("source_article_id"),
                    "created_at": created_at,
                }
            )
        return relations

    async def get_related_entities(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get entities mentioned in same articles.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of entities.

        Returns:
            List of entity dicts.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_related_entities_query(),
            {"name": canonical_name, "limit": limit},
        )
        entities = []
        for row in result:
            updated_at = convert_timestamp(row.get("updated_at"))
            created_at = convert_timestamp(row.get("created_at"))

            entities.append(
                {
                    "id": row.get("id") or "",
                    "canonical_name": row.get("canonical_name") or "",
                    "type": row.get("type") or "未知",
                    "aliases": row.get("aliases"),
                    "description": row.get("description"),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )

        # Remove duplicates based on entity ID
        seen_ids = set()
        deduplicated = []
        for entity in entities:
            entity_id = entity.get("id")
            if entity_id and entity_id not in seen_ids:
                seen_ids.add(entity_id)
                deduplicated.append(entity)

        return deduplicated

    async def get_relation_types(self, entity_name: str, entity_type: str) -> list[dict[str, Any]]:
        """Get all relation types for an entity.

        Args:
            entity_name: Entity canonical name.
            entity_type: Entity type.

        Returns:
            List of relation type summaries.
        """
        result = await self._execute_fn(
            lambda qb: qb.build_get_relation_types_query(),
            {"name": entity_name, "type": entity_type},
        )
        return [
            {
                "relation_type": r["relation_type"],
                "target_count": r["target_count"],
                "primary_direction": r["primary_direction"],
            }
            for r in result
        ]

    async def find_by_relation_types(
        self,
        entity_name: str,
        entity_type: str | None = None,
        relation_types: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Find related entities by relation types.

        Args:
            entity_name: Entity canonical name.
            entity_type: Entity type (optional, matched by canonical_name only if None).
            relation_types: Optional list of relation types to filter.
            limit: Maximum number of results.

        Returns:
            List of related entity dicts with computed co-occurrence weight.
        """
        params: dict[str, Any] = {"name": entity_name, "limit": limit}
        if entity_type is not None:
            params["type"] = entity_type
        result = await self._execute_fn(
            lambda qb: qb.build_find_by_relation_types_query(relation_types, entity_type),
            params,
        )

        # Compute weight dynamically as co-occurrence article count
        # Find articles that mention both the source entity and each target
        weights = await self._compute_cooccurrence_weights(
            entity_name, [r["target_name"] for r in result]
        )

        # Use stored weight when it's been computed (weight > 1.0),
        # otherwise fall back to co-occurrence calculation for default 1.0 weights
        return [
            {
                "relation_type": r["relation_type"],
                "direction": r["direction"],
                "target_name": r["target_name"],
                "target_type": r["target_type"],
                "target_description": r.get("target_description"),
                "weight": (
                    r.get("weight", 1.0)
                    if r.get("weight", 1.0) > 1.0
                    else weights.get(r["target_name"], r.get("weight", 1.0))
                ),
            }
            for r in result
        ]

    async def _compute_cooccurrence_weights(
        self, source_name: str, target_names: list[str]
    ) -> dict[str, float]:
        """Compute co-occurrence weights as shared article counts.

        Uses a single Cypher query to count shared articles between the source
        entity and all target entities. Works with both Neo4j and LadybugDB.

        Args:
            source_name: Source entity canonical name.
            target_names: List of target entity canonical names.

        Returns:
            Dict mapping target name to co-occurrence count.
        """
        if not target_names:
            return {}

        try:
            # Single query: count shared articles between source and all targets
            query = """
                MATCH (a:Article)-[:MENTIONS]->(src:Entity {canonical_name: $source})
                WITH a, collect(DISTINCT src) AS sources
                MATCH (a)-[:MENTIONS]->(tgt:Entity)
                WHERE tgt.canonical_name IN $targets
                RETURN tgt.canonical_name AS target_name,
                       count(DISTINCT a) AS shared_count
            """
            result = await self._pool.execute_query(
                query,
                {"source": source_name, "targets": target_names},
            )

            weights: dict[str, float] = {}
            for row in result:
                target_name = row.get("target_name")
                shared_count = row.get("shared_count", 0)
                if target_name and shared_count:
                    weights[target_name] = float(shared_count)

            return weights
        except Exception:
            log.warning("calculate_entity_co_occurrence_failed", exc_info=True)
            # Fallback: return empty, stored weight will be used
            return {}
