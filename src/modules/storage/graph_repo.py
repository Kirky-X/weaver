# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Abstract graph repository using QueryBuilder pattern.

Provides database-agnostic graph operations by delegating query building
to GraphQueryBuilder implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.db.graph_query_builders import GraphQueryBuilder
from core.observability.logging import get_logger

if TYPE_CHECKING:
    from core.protocols import GraphPool

log = get_logger("graph_repo")


class GraphRepository:
    """Database-agnostic graph repository.

    Handles entity and article graph operations using the QueryBuilder pattern
    to abstract Neo4j/LadybugDB syntax differences.

    Supports automatic fallback: if the primary database (Neo4j) returns
    empty results, queries the fallback (LadybugDB).

    Args:
        pool: Primary graph database pool (Neo4j or LadybugDB).
        query_builder: Database-specific query builder for primary.
        fallback_pool: Optional fallback pool (LadybugDB when Neo4j is primary).
        fallback_query_builder: Optional query builder for fallback.
    """

    def __init__(
        self,
        pool: GraphPool,
        query_builder: GraphQueryBuilder,
        fallback_pool: GraphPool | None = None,
        fallback_query_builder: GraphQueryBuilder | None = None,
    ) -> None:
        self._pool = pool
        self._query_builder = query_builder
        self._fallback_pool = fallback_pool
        self._fallback_query_builder = fallback_query_builder

    @property
    def database_type(self) -> str:
        """Get the database type."""
        return self._query_builder.database_type.value

    async def _execute_with_fallback(
        self,
        build_query_fn: Any,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute query on primary, fallback if empty."""
        query = build_query_fn(self._query_builder)
        result = await self._pool.execute_query(query, params or {})
        if result or self._fallback_query_builder is None:
            return result
        try:
            fb_query = build_query_fn(self._fallback_query_builder)
            return await self._fallback_pool.execute_query(fb_query, params or {})
        except Exception as exc:
            log.warning("graph_repo_fallback_failed", error=str(exc))
            return result

    # ── Entity Operations ─────────────────────────────────────────────

    async def get_entity(self, canonical_name: str) -> dict[str, Any] | None:
        """Get entity by canonical name.

        Args:
            canonical_name: Entity canonical name.

        Returns:
            Entity dict or None if not found.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_entity_query(),
            {"name": canonical_name},
        )
        if result:
            record = result[0]
            updated_at = record.get("updated_at")
            if updated_at is not None:
                # LadybugDB stores as INT64 seconds, Neo4j as datetime
                if isinstance(updated_at, int):
                    from datetime import UTC, datetime

                    # Auto-detect: seconds (< 10^11) vs ms (> 10^12)
                    if updated_at > 1_000_000_000_000:
                        updated_at = datetime.fromtimestamp(updated_at / 1000, tz=UTC).isoformat()
                    else:
                        updated_at = datetime.fromtimestamp(updated_at, tz=UTC).isoformat()
                elif hasattr(updated_at, "isoformat"):
                    updated_at = updated_at.isoformat()
                else:
                    updated_at = str(updated_at)

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
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_entity_relations_query(),
            {"name": canonical_name, "limit": limit},
        )
        relations = []
        for row in result:
            created_at = row.get("created_at")
            if created_at is not None:
                if isinstance(created_at, int):
                    from datetime import UTC, datetime

                    # Auto-detect: seconds (< 10^11) vs ms (> 10^12)
                    if created_at > 1_000_000_000_000:
                        created_at = datetime.fromtimestamp(created_at / 1000, tz=UTC).isoformat()
                    else:
                        created_at = datetime.fromtimestamp(created_at, tz=UTC).isoformat()
                elif hasattr(created_at, "isoformat"):
                    created_at = created_at.isoformat()
                else:
                    created_at = str(created_at)
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
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_related_entities_query(),
            {"name": canonical_name, "limit": limit},
        )
        entities = []
        for row in result:
            # Handle timestamps (LadybugDB stores as INT64 seconds)
            updated_at = row.get("updated_at")
            created_at = row.get("created_at")
            for ts_field, ts_val in [("updated_at", updated_at), ("created_at", created_at)]:
                if ts_val is not None and isinstance(ts_val, int):
                    from datetime import UTC, datetime

                    if ts_val > 1_000_000_000_000:
                        ts_val = datetime.fromtimestamp(ts_val / 1000, tz=UTC).isoformat()
                    else:
                        ts_val = datetime.fromtimestamp(ts_val, tz=UTC).isoformat()
                    if ts_field == "updated_at":
                        updated_at = ts_val
                    else:
                        created_at = ts_val

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
        return entities

    async def get_entity_articles(
        self, canonical_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Get articles mentioning an entity.

        Args:
            canonical_name: Entity canonical name.
            limit: Maximum number of articles.

        Returns:
            List of article dicts.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_entity_articles_query(),
            {"name": canonical_name, "limit": limit},
        )
        articles = []
        for row in result:
            publish_time = row.get("publish_time")
            if publish_time is not None:
                if isinstance(publish_time, int):
                    from datetime import UTC, datetime

                    # LadybugDB stores publish_time as INT64 seconds (not ms)
                    # Check if value looks like seconds (< 10^11) vs ms (> 10^12)
                    if publish_time > 1_000_000_000_000:
                        publish_time = datetime.fromtimestamp(
                            publish_time / 1000, tz=UTC
                        ).isoformat()
                    else:
                        publish_time = datetime.fromtimestamp(publish_time, tz=UTC).isoformat()
                elif hasattr(publish_time, "isoformat"):
                    publish_time = publish_time.isoformat()
                else:
                    publish_time = str(publish_time)
            articles.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "category": row.get("category"),
                    "publish_time": publish_time,
                    "score": row.get("score"),
                }
            )
        return articles

    # ── Article Graph Operations ───────────────────────────────────────

    async def get_article(self, article_id: str) -> dict[str, Any] | None:
        """Get article node from graph.

        Args:
            article_id: Article UUID (pg_id).

        Returns:
            Article dict or None if not found.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_article_graph_query(),
            {"id": article_id},
        )
        if result:
            record = result[0]
            publish_time = record.get("publish_time")
            if publish_time is not None:
                if isinstance(publish_time, int):
                    from datetime import UTC, datetime

                    # LadybugDB stores publish_time as INT64 seconds (not ms)
                    publish_time = datetime.fromtimestamp(publish_time, tz=UTC).isoformat()
                elif hasattr(publish_time, "isoformat"):
                    publish_time = publish_time.isoformat()
                else:
                    publish_time = str(publish_time)

            return {
                "id": record.get("id") or "",
                "title": record.get("title") or "",
                "category": record.get("category"),
                "publish_time": publish_time,
                "score": record.get("score"),
            }
        return None

    async def get_article_entities(self, article_id: str) -> list[dict[str, Any]]:
        """Get entities mentioned in an article.

        Args:
            article_id: Article UUID.

        Returns:
            List of entity dicts.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_article_entities_query(),
            {"id": article_id},
        )
        entities = []
        for row in result:
            # Handle timestamps (LadybugDB stores as INT64 seconds)
            updated_at = row.get("updated_at")
            created_at = row.get("created_at")
            for ts_field in ["updated_at", "created_at"]:
                ts = row.get(ts_field)
                if ts is not None and isinstance(ts, int):
                    from datetime import UTC, datetime

                    if ts > 1_000_000_000_000:
                        ts = datetime.fromtimestamp(ts / 1000, tz=UTC).isoformat()
                    else:
                        ts = datetime.fromtimestamp(ts, tz=UTC).isoformat()
                    if ts_field == "updated_at":
                        updated_at = ts
                    else:
                        created_at = ts

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
        return entities

    async def get_article_relationships(self, article_id: str) -> list[dict[str, Any]]:
        """Get relationships between entities in an article.

        Args:
            article_id: Article UUID.

        Returns:
            List of relationship dicts.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_article_relationships_query(),
            {"id": article_id},
        )
        relationships = []
        for row in result:
            created_at = row.get("created_at")
            if created_at is not None:
                if isinstance(created_at, int):
                    from datetime import UTC, datetime

                    # Auto-detect: seconds (< 10^11) vs ms (> 10^12)
                    if created_at > 1_000_000_000_000:
                        created_at = datetime.fromtimestamp(created_at / 1000, tz=UTC).isoformat()
                    else:
                        created_at = datetime.fromtimestamp(created_at, tz=UTC).isoformat()
                elif hasattr(created_at, "isoformat"):
                    created_at = created_at.isoformat()
                else:
                    created_at = str(created_at)
            relationships.append(
                {
                    "source_id": row["source"],
                    "target_id": row["target"],
                    "relation_type": row["relation_type"] or "RELATED_TO",
                    "properties": {
                        "source_article_id": row.get("source_article_id"),
                        "created_at": created_at,
                    },
                }
            )
        return relationships

    async def get_related_articles(self, article_id: str) -> list[dict[str, Any]]:
        """Get related articles.

        Args:
            article_id: Article UUID.

        Returns:
            List of article dicts.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_get_related_articles_query(),
            {"id": article_id},
        )
        articles = []
        for row in result:
            publish_time = row.get("publish_time")
            if publish_time is not None:
                if isinstance(publish_time, int):
                    from datetime import UTC, datetime

                    # LadybugDB stores publish_time as INT64 seconds (not ms)
                    # Check if value looks like seconds (< 10^11) vs ms (> 10^12)
                    if publish_time > 1_000_000_000_000:
                        publish_time = datetime.fromtimestamp(
                            publish_time / 1000, tz=UTC
                        ).isoformat()
                    else:
                        publish_time = datetime.fromtimestamp(publish_time, tz=UTC).isoformat()
                elif hasattr(publish_time, "isoformat"):
                    publish_time = publish_time.isoformat()
                else:
                    publish_time = str(publish_time)
            articles.append(
                {
                    "id": row.get("id") or "",
                    "title": row.get("title") or "",
                    "category": row.get("category"),
                    "publish_time": publish_time,
                    "score": row.get("score"),
                }
            )
        return articles

    # ── Relation Type Operations ────────────────────────────────────────

    async def get_relation_types(self, entity_name: str, entity_type: str) -> list[dict[str, Any]]:
        """Get all relation types for an entity.

        Args:
            entity_name: Entity canonical name.
            entity_type: Entity type.

        Returns:
            List of relation type summaries.
        """
        result = await self._execute_with_fallback(
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
        result = await self._execute_with_fallback(
            lambda qb: qb.build_find_by_relation_types_query(relation_types, entity_type),
            params,
        )

        # Compute weight dynamically as co-occurrence article count
        # Find articles that mention both the source entity and each target
        weights = await self._compute_cooccurrence_weights(
            entity_name, [r["target_name"] for r in result]
        )

        return [
            {
                "relation_type": r["relation_type"],
                "direction": r["direction"],
                "target_name": r["target_name"],
                "target_type": r["target_type"],
                "target_description": r.get("target_description"),
                "weight": weights.get(r["target_name"], r.get("weight", 1.0)),
            }
            for r in result
        ]

    async def _compute_cooccurrence_weights(
        self, source_name: str, target_names: list[str]
    ) -> dict[str, float]:
        """Compute co-occurrence weights as shared article counts.

        Uses two-pass approach: get articles mentioning source, then check
        which of those also mention each target. Works with LadybugDB.

        Args:
            source_name: Source entity canonical name.
            target_names: List of target entity canonical names.

        Returns:
            Dict mapping target name to co-occurrence count.
        """
        if not target_names:
            return {}

        try:
            # Get articles mentioning source entity
            source_articles_query = """
                MATCH (a:Article)-[:MENTIONS]->(src:Entity {canonical_name: $name})
                RETURN DISTINCT a.pg_id AS article_id
            """
            source_result = await self._pool.execute_query(
                source_articles_query, {"name": source_name}
            )
            if not source_result:
                return {}

            source_article_ids = {row["article_id"] for row in source_result}
            if not source_article_ids:
                return {}

            # For each target, count shared articles
            weights = {}
            for target in target_names:
                target_articles_query = """
                    MATCH (a:Article)-[:MENTIONS]->(tgt:Entity {canonical_name: $target})
                    RETURN DISTINCT a.pg_id AS article_id
                """
                target_result = await self._pool.execute_query(
                    target_articles_query, {"target": target}
                )
                target_article_ids = {row["article_id"] for row in target_result}
                shared = source_article_ids & target_article_ids
                if shared:
                    weights[target] = float(len(shared))

            return weights
        except Exception:
            # Fallback: return empty, stored weight will be used
            return {}

    # ── Visualization Operations ───────────────────────────────────────

    async def get_visualization_nodes(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get nodes for graph visualization.

        Args:
            limit: Maximum number of nodes to return.

        Returns:
            List of node dicts with id, label, type, description, and degree.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_visualization_nodes_query(),
            {"limit": limit},
        )
        nodes = []
        for row in result:
            nodes.append(
                {
                    "id": row.get("id") or "",
                    "label": row.get("label") or "",
                    "type": row.get("type") or "未知",
                    "description": row.get("description"),
                    "degree": row.get("degree", 0),
                }
            )
        return nodes

    async def get_visualization_edges(
        self, node_ids: list[str], edge_limit: int = 300
    ) -> list[dict[str, Any]]:
        """Get edges for graph visualization.

        Args:
            node_ids: List of node canonical names to filter edges.
            edge_limit: Maximum number of edges to return.

        Returns:
            List of edge dicts with source, target, relation_type, and weight.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_visualization_edges_query(),
            {"node_ids": node_ids, "edge_limit": edge_limit},
        )
        edges = []
        for row in result:
            edges.append(
                {
                    "source": row.get("source") or "",
                    "target": row.get("target") or "",
                    "relation_type": row.get("relation_type") or "RELATED_TO",
                    "weight": row.get("weight"),
                }
            )
        return edges

    async def get_subgraph_nodes(
        self,
        center_entity: str,
        hop_pattern: str,
        include_types: list[str] | None = None,
        exclude_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get nodes for subgraph extraction around a center entity.

        Args:
            center_entity: Center entity canonical name.
            hop_pattern: Hop pattern like '*1..1', '*1..2', etc.
            include_types: Optional list of entity types to include.
            exclude_types: Optional list of entity types to exclude (applied in Python).

        Returns:
            List of node dicts with id, label, type, and description.
        """
        params: dict[str, Any] = {"center": center_entity}
        if include_types:
            params["include_types"] = include_types
        result = await self._execute_with_fallback(
            lambda qb: qb.build_subgraph_nodes_query(hop_pattern, include_types is not None),
            params,
        )
        nodes = []
        for row in result:
            entity_type = row.get("type") or "未知"
            if exclude_types and entity_type in exclude_types:
                continue
            nodes.append(
                {
                    "id": row.get("id") or "",
                    "label": row.get("label") or "",
                    "type": entity_type,
                    "description": row.get("description"),
                }
            )
        return nodes

    async def get_subgraph_edges(self, node_ids: list[str]) -> list[dict[str, Any]]:
        """Get edges for subgraph visualization.

        Args:
            node_ids: List of node canonical names to filter edges.

        Returns:
            List of edge dicts with source, target, relation_type, and weight.
        """
        result = await self._execute_with_fallback(
            lambda qb: qb.build_subgraph_edges_query(),
            {"node_ids": node_ids},
        )
        edges = []
        for row in result:
            edges.append(
                {
                    "source": row.get("source") or "",
                    "target": row.get("target") or "",
                    "relation_type": row.get("relation_type") or "RELATED_TO",
                    "weight": row.get("weight"),
                }
            )
        return edges
