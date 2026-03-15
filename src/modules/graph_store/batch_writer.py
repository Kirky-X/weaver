"""Neo4j batch writer for efficient bulk operations.

Provides optimized batch operations using UNWIND for bulk inserts/updates,
significantly improving performance for large-scale entity and relationship operations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger

log = get_logger("neo4j.batch_writer")


@dataclass
class BatchResult:
    """Result of a batch operation."""

    total: int
    created: int
    updated: int
    skipped: int
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total == 0:
            return 1.0
        return (self.created + self.updated) / self.total


@dataclass
class EntityBatch:
    """Batch of entities to process."""

    canonical_name: str
    entity_type: str
    description: str | None = None
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationBatch:
    """Batch of relationships to process."""

    from_name: str
    from_type: str
    to_name: str
    to_type: str
    relation_type: str
    properties: dict[str, Any] = field(default_factory=dict)


class Neo4jBatchWriter:
    """Efficient batch writer for Neo4j operations.

    Uses UNWIND for bulk operations, reducing round-trips and
    improving throughput for large-scale data ingestion.

    Default batch sizes:
    - Entities: 1000 per batch
    - Relationships: 2000 per batch
    - Mentions: 5000 per batch
    """

    DEFAULT_ENTITY_BATCH_SIZE = 1000
    DEFAULT_RELATION_BATCH_SIZE = 2000
    DEFAULT_MENTIONS_BATCH_SIZE = 5000

    def __init__(
        self,
        pool: Neo4jPool,
        entity_batch_size: int | None = None,
        relation_batch_size: int | None = None,
        mentions_batch_size: int | None = None,
    ) -> None:
        """Initialize batch writer.

        Args:
            pool: Neo4j connection pool.
            entity_batch_size: Batch size for entity operations.
            relation_batch_size: Batch size for relationship operations.
            mentions_batch_size: Batch size for mentions operations.
        """
        self._pool = pool
        self._entity_batch_size = entity_batch_size or self.DEFAULT_ENTITY_BATCH_SIZE
        self._relation_batch_size = relation_batch_size or self.DEFAULT_RELATION_BATCH_SIZE
        self._mentions_batch_size = mentions_batch_size or self.DEFAULT_MENTIONS_BATCH_SIZE

    async def merge_entities_batch(
        self,
        entities: list[EntityBatch],
    ) -> BatchResult:
        """Merge multiple entities in batches.

        Uses UNWIND for efficient bulk MERGE operations.

        Args:
            entities: List of EntityBatch objects to merge.

        Returns:
            BatchResult with operation statistics.
        """
        if not entities:
            return BatchResult(total=0, created=0, updated=0, skipped=0)

        result = BatchResult(total=len(entities), created=0, updated=0, skipped=0)

        for batch in self._chunk(entities, self._entity_batch_size):
            try:
                batch_result = await self._merge_entity_chunk(batch)
                result.created += batch_result.get("created", 0)
                result.updated += batch_result.get("updated", 0)
            except Exception as exc:
                log.error("batch_entity_merge_failed", error=str(exc))
                result.errors.append(str(exc))
                result.skipped += len(batch)

        return result

    async def _merge_entity_chunk(
        self,
        entities: list[EntityBatch],
    ) -> dict[str, int]:
        """Merge a chunk of entities using UNWIND."""
        query = """
        UNWIND $entities AS entity
        MERGE (e:Entity {canonical_name: entity.canonical_name, type: entity.type})
        ON CREATE SET
            e.id = entity.id,
            e.aliases = entity.aliases,
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
        WITH e, entity,
             CASE WHEN e.created_at = e.updated_at THEN 1 ELSE 0 END AS is_new
        UNWIND CASE
            WHEN entity.additional_aliases IS NOT NULL AND size(entity.additional_aliases) > 0
            THEN entity.additional_aliases
            ELSE [NULL]
        END AS alias
        WITH e, is_new, alias
        WHERE alias IS NOT NULL AND NOT alias IN e.aliases
        SET e.aliases = e.aliases + alias
        RETURN sum(is_new) AS created, count(e) - sum(is_new) AS updated
        """

        params = {
            "entities": [
                {
                    "canonical_name": e.canonical_name,
                    "type": e.entity_type,
                    "id": str(uuid.uuid4()),
                    "description": e.description,
                    "aliases": [e.canonical_name],
                    "additional_aliases": [a for a in e.aliases if a != e.canonical_name],
                }
                for e in entities
            ]
        }

        result = await self._pool.execute_query(query, params)
        if result:
            return {
                "created": result[0].get("created", 0),
                "updated": result[0].get("updated", 0),
            }
        return {"created": 0, "updated": 0}

    async def merge_relations_batch(
        self,
        relations: list[RelationBatch],
    ) -> BatchResult:
        """Merge multiple relationships in batches.

        Args:
            relations: List of RelationBatch objects to merge.

        Returns:
            BatchResult with operation statistics.
        """
        if not relations:
            return BatchResult(total=0, created=0, updated=0, skipped=0)

        result = BatchResult(total=len(relations), created=0, updated=0, skipped=0)

        for batch in self._chunk(relations, self._relation_batch_size):
            try:
                batch_result = await self._merge_relation_chunk(batch)
                result.created += batch_result.get("created", 0)
                result.updated += batch_result.get("updated", 0)
            except Exception as exc:
                log.error("batch_relation_merge_failed", error=str(exc))
                result.errors.append(str(exc))
                result.skipped += len(batch)

        return result

    async def _merge_relation_chunk(
        self,
        relations: list[RelationBatch],
    ) -> dict[str, int]:
        """Merge a chunk of relationships using UNWIND."""
        query = """
        UNWIND $relations AS rel
        MATCH (from:Entity {canonical_name: rel.from_name, type: rel.from_type})
        MATCH (to:Entity {canonical_name: rel.to_name, type: rel.to_type})
        MERGE (from)-[r:RELATED_TO {relation_type: rel.relation_type}]->(to)
        ON CREATE SET
            r.created_at = datetime(),
            r.updated_at = datetime()
        ON MATCH SET
            r.updated_at = datetime()
        SET r += rel.properties
        RETURN count(r) AS total
        """

        params = {
            "relations": [
                {
                    "from_name": r.from_name,
                    "from_type": r.from_type,
                    "to_name": r.to_name,
                    "to_type": r.to_type,
                    "relation_type": r.relation_type,
                    "properties": r.properties,
                }
                for r in relations
            ]
        }

        result = await self._pool.execute_query(query, params)
        if result:
            return {"created": result[0].get("total", 0), "updated": 0}
        return {"created": 0, "updated": 0}

    async def merge_mentions_batch(
        self,
        mentions: list[dict[str, Any]],
    ) -> BatchResult:
        """Merge multiple MENTIONS relationships in batches.

        Args:
            mentions: List of dicts with 'article_id', 'entity_name', 'entity_type', 'role'.

        Returns:
            BatchResult with operation statistics.
        """
        if not mentions:
            return BatchResult(total=0, created=0, updated=0, skipped=0)

        result = BatchResult(total=len(mentions), created=0, updated=0, skipped=0)

        for batch in self._chunk(mentions, self._mentions_batch_size):
            try:
                batch_result = await self._merge_mentions_chunk(batch)
                result.created += batch_result.get("created", 0)
            except Exception as exc:
                log.error("batch_mentions_merge_failed", error=str(exc))
                result.errors.append(str(exc))
                result.skipped += len(batch)

        return result

    async def _merge_mentions_chunk(
        self,
        mentions: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Merge a chunk of MENTIONS relationships using UNWIND."""
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
                for m in mentions
            ]
        }

        result = await self._pool.execute_query(query, params)
        if result:
            return {"created": result[0].get("total", 0)}
        return {"created": 0}

    async def add_aliases_batch(
        self,
        aliases: list[dict[str, Any]],
    ) -> BatchResult:
        """Add aliases to multiple entities in batch.

        Args:
            aliases: List of dicts with 'canonical_name', 'entity_type', 'alias'.

        Returns:
            BatchResult with operation statistics.
        """
        if not aliases:
            return BatchResult(total=0, created=0, updated=0, skipped=0)

        result = BatchResult(total=len(aliases), created=0, updated=0, skipped=0)

        for batch in self._chunk(aliases, self._entity_batch_size):
            try:
                batch_result = await self._add_aliases_chunk(batch)
                result.updated += batch_result.get("updated", 0)
            except Exception as exc:
                log.error("batch_aliases_add_failed", error=str(exc))
                result.errors.append(str(exc))
                result.skipped += len(batch)

        return result

    async def _add_aliases_chunk(
        self,
        aliases: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Add a chunk of aliases using UNWIND."""
        query = """
        UNWIND $aliases AS alias_data
        MATCH (e:Entity {canonical_name: alias_data.canonical_name, type: alias_data.entity_type})
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
                    "entity_type": a.get("entity_type"),
                    "alias": a.get("alias"),
                }
                for a in aliases
            ]
        }

        result = await self._pool.execute_query(query, params)
        if result:
            return {"updated": result[0].get("updated", 0)}
        return {"updated": 0}

    async def update_entity_embeddings_batch(
        self,
        embeddings: list[dict[str, Any]],
    ) -> BatchResult:
        """Update embeddings for multiple entities.

        Note: This updates the embedding property on Entity nodes.
        For vector search, use VectorRepo instead.

        Args:
            embeddings: List of dicts with 'entity_name', 'entity_type', 'embedding'.

        Returns:
            BatchResult with operation statistics.
        """
        if not embeddings:
            return BatchResult(total=0, created=0, updated=0, skipped=0)

        result = BatchResult(total=len(embeddings), created=0, updated=0, skipped=0)

        for batch in self._chunk(embeddings, self._entity_batch_size):
            try:
                batch_result = await self._update_embeddings_chunk(batch)
                result.updated += batch_result.get("updated", 0)
            except Exception as exc:
                log.error("batch_embeddings_update_failed", error=str(exc))
                result.errors.append(str(exc))
                result.skipped += len(batch)

        return result

    async def _update_embeddings_chunk(
        self,
        embeddings: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Update a chunk of entity embeddings."""
        query = """
        UNWIND $embeddings AS emb
        MATCH (e:Entity {canonical_name: emb.entity_name, type: emb.entity_type})
        SET e.embedding = emb.embedding, e.updated_at = datetime()
        RETURN count(e) AS updated
        """

        params = {
            "embeddings": [
                {
                    "entity_name": e.get("entity_name"),
                    "entity_type": e.get("entity_type"),
                    "embedding": e.get("embedding"),
                }
                for e in embeddings
            ]
        }

        result = await self._pool.execute_query(query, params)
        if result:
            return {"updated": result[0].get("updated", 0)}
        return {"updated": 0}

    async def delete_entities_batch(
        self,
        entity_ids: list[str],
    ) -> int:
        """Delete multiple entities by their Neo4j IDs.

        Args:
            entity_ids: List of Neo4j internal element IDs.

        Returns:
            Number of entities deleted.
        """
        if not entity_ids:
            return 0

        total_deleted = 0

        for batch in self._chunk(entity_ids, self._entity_batch_size):
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

    async def create_article_entities_batch(
        self,
        articles: list[dict[str, Any]],
    ) -> BatchResult:
        """Create multiple Article nodes in batch.

        Args:
            articles: List of article dicts with 'pg_id', 'title', etc.

        Returns:
            BatchResult with operation statistics.
        """
        if not articles:
            return BatchResult(total=0, created=0, updated=0, skipped=0)

        result = BatchResult(total=len(articles), created=0, updated=0, skipped=0)

        for batch in self._chunk(articles, self._entity_batch_size):
            try:
                batch_result = await self._create_articles_chunk(batch)
                result.created += batch_result.get("created", 0)
                result.updated += batch_result.get("updated", 0)
            except Exception as exc:
                log.error("batch_article_create_failed", error=str(exc))
                result.errors.append(str(exc))
                result.skipped += len(batch)

        return result

    async def _create_articles_chunk(
        self,
        articles: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Create a chunk of Article nodes."""
        query = """
        UNWIND $articles AS article
        MERGE (a:Article {pg_id: article.pg_id})
        ON CREATE SET
            a.title = article.title,
            a.category = article.category,
            a.publish_time = article.publish_time,
            a.score = article.score,
            a.created_at = datetime(),
            a.updated_at = datetime()
        ON MATCH SET
            a.title = article.title,
            a.category = article.category,
            a.score = article.score,
            a.updated_at = datetime()
        WITH a, CASE WHEN a.created_at = a.updated_at THEN 1 ELSE 0 END AS is_new
        RETURN sum(is_new) AS created, count(a) - sum(is_new) AS updated
        """

        params = {
            "articles": [
                {
                    "pg_id": a.get("pg_id"),
                    "title": a.get("title"),
                    "category": a.get("category"),
                    "publish_time": a.get("publish_time"),
                    "score": a.get("score"),
                }
                for a in articles
            ]
        }

        result = await self._pool.execute_query(query, params)
        if result:
            return {
                "created": result[0].get("created", 0),
                "updated": result[0].get("updated", 0),
            }
        return {"created": 0, "updated": 0}

    @staticmethod
    def _chunk(items: list[Any], size: int) -> Iterator[list[Any]]:
        """Split items into chunks of specified size."""
        for i in range(0, len(items), size):
            yield items[i:i + size]
