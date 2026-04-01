# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Neo4j writer for persisting pipeline state to graph database."""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger
from modules.processing.pipeline.state import PipelineState
from modules.storage.neo4j.article_repo import Neo4jArticleRepo
from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

if TYPE_CHECKING:
    from modules.knowledge.core.relation_types import RelationTypeNormalizer

log = get_logger("neo4j_writer")


class Neo4jWriter:
    """Writes pipeline processing results to Neo4j graph database.

    Coordinates entity and article repositories to persist:
    - Article nodes with metadata
    - Entity nodes from extraction
    - MENTIONS relationships (article -> entity)
    - FOLLOWED_BY relationships (article -> article)
    - Typed entity-to-entity relationships (normalised via RelationTypeNormalizer)

    Args:
        pool: Neo4j connection pool.
        relation_type_normalizer: Optional normaliser for relation types.
            When provided, LLM-extracted relation types are normalised
            before writing to Neo4j.
    """

    def __init__(
        self,
        pool: Neo4jPool,
        relation_type_normalizer: RelationTypeNormalizer | None = None,
    ) -> None:
        self._pool = pool
        self._entity_repo = Neo4jEntityRepo(pool)
        self._article_repo = Neo4jArticleRepo(pool)
        self._normalizer = relation_type_normalizer

    @property
    def entity_repo(self) -> Neo4jEntityRepo:
        """Get the entity repository."""
        return self._entity_repo

    @property
    def article_repo(self) -> Neo4jArticleRepo:
        """Get the article repository."""
        return self._article_repo

    async def ensure_constraints(self) -> None:
        """Ensure Neo4j constraints exist."""
        await self._entity_repo.ensure_constraints()

    async def write(self, state: PipelineState) -> list[str]:
        """Write pipeline state to Neo4j.

        Creates article node, processes entities, and establishes relationships.

        Args:
            state: Pipeline state containing article and entity data.

        Returns:
            List of Neo4j entity IDs created/resolved.
        """
        article_id = state.get("article_id")
        if not article_id:
            raise ValueError("article_id not found in pipeline state")

        article_id_str = str(article_id)

        log.info("neo4j_write_start", article_id=article_id_str)

        neo4j_ids: list[str] = []

        raw = state["raw"]
        title = state.get("cleaned", {}).get("title", raw.title)
        category = state.get("category", "unknown")
        publish_time = raw.publish_time
        score = state.get("score")

        article_neo4j_id = await self._article_repo.create_article(
            pg_id=article_id_str,
            title=title,
            category=category.value if hasattr(category, "value") else str(category),
            publish_time=publish_time,
            score=score,
        )
        log.debug("neo4j_article_created", article_id=article_id_str)

        # 2. Process entities and create MENTIONS relationships
        entities = state.get("entities", [])
        if entities:
            entity_ids = await self._write_entities(
                article_neo4j_id=article_neo4j_id,
                entities=entities,
                state=state,
            )
            neo4j_ids.extend(entity_ids)

        # 3. Handle FOLLOWED_BY relationships
        merged_source_ids = state.get("merged_source_ids", [])
        if merged_source_ids:
            await self._create_followed_relations(
                article_id=article_id_str,
                source_ids=merged_source_ids,
                publish_time=publish_time,
            )

        log.info("neo4j_write_complete", article_id=article_id_str, entity_count=len(neo4j_ids))
        return neo4j_ids

    async def _write_entities(
        self,
        article_neo4j_id: str,
        entities: list[dict[str, Any]],
        state: PipelineState,
    ) -> list[str]:
        """Write entities and create MENTIONS relationships using batch operations.

        Args:
            article_neo4j_id: The article's Neo4j ID.
            entities: List of entity dicts from entity extractor.
            state: Pipeline state for additional context.

        Returns:
            List of entity Neo4j IDs.
        """
        if not entities:
            return []

        entity_name_to_id: dict[str, str] = {}

        entity_data = []
        alias_data = []
        mentions_data = []

        for entity in entities:
            name = entity.get("name")
            entity_type = entity.get("type")
            role = entity.get("role")

            if not name or not entity_type:
                continue

            canonical_name = await self._resolve_canonical_name(name, entity_type)

            entity_data.append(
                {
                    "canonical_name": canonical_name,
                    "type": entity_type,
                    "description": entity.get("description"),
                }
            )

            if name != canonical_name:
                alias_data.append(
                    {
                        "canonical_name": canonical_name,
                        "type": entity_type,
                        "alias": name,
                    }
                )

            mentions_data.append(
                {
                    "canonical_name": canonical_name,
                    "type": entity_type,
                    "role": role,
                }
            )

        if entity_data:
            try:
                result = await self._entity_repo.merge_entities_batch(entity_data)
                log.info(
                    "neo4j_entities_batch_merged",
                    created=result.get("created", 0),
                    updated=result.get("updated", 0),
                )
            except Exception as exc:
                log.error("neo4j_entities_batch_failed", error=str(exc))
                return []

        if alias_data:
            try:
                await self._entity_repo.add_aliases_batch(alias_data)
            except Exception as exc:
                log.warning("neo4j_aliases_batch_failed", error=str(exc))

        entity_ids: list[str] = []
        for entity in entity_data:
            existing = await self._entity_repo.find_entity(
                entity["canonical_name"],
                entity["type"],
            )
            if existing:
                entity_ids.append(existing["neo4j_id"])
                entity_name_to_id[entity["canonical_name"]] = existing["neo4j_id"]

        if mentions_data and entity_name_to_id:
            mentions_with_ids = [
                {
                    "article_id": state.get("article_id"),
                    "entity_name": m["canonical_name"],
                    "entity_type": m["type"],
                    "role": m.get("role"),
                }
                for m in mentions_data
                if m["canonical_name"] in entity_name_to_id
            ]
            if mentions_with_ids:
                try:
                    count = await self._entity_repo.merge_mentions_batch(mentions_with_ids)
                    log.info("neo4j_mentions_batch_created", count=count)
                except Exception as exc:
                    log.error("neo4j_mentions_batch_failed", error=str(exc))

        relations = state.get("relations", [])
        if relations and entity_name_to_id:
            await self._write_entity_relations(relations, entity_name_to_id)

        return entity_ids

    async def _write_entity_relations(
        self,
        relations: list[dict[str, Any]],
        entity_name_to_id: dict[str, str],
    ) -> int:
        """Write entity-to-entity relationships to Neo4j.

        When a ``RelationTypeNormalizer`` is available each LLM-extracted
        relation type is normalised before writing.  Unknown types are
        recorded for later review.

        Args:
            relations: List of relation dicts from entity extractor.
            entity_name_to_id: Mapping from entity canonical name to Neo4j ID.

        Returns:
            Number of relations created.
        """
        count = 0
        for relation in relations:
            source_name = relation.get("source")
            target_name = relation.get("target")
            relation_type = relation.get("relation_type")

            if not source_name or not target_name or not relation_type:
                continue

            # Normalise relation type
            edge_type = relation_type
            raw_type = relation_type
            direction = "unidirectional"

            if self._normalizer:
                try:
                    normalized = await self._normalizer.normalize(relation_type)
                    if normalized.name_en:
                        edge_type = normalized.name_en
                    else:
                        edge_type = relation_type
                        ctx = f"{source_name}\u2192{target_name}"
                        await self._normalizer.record_unknown(relation_type, ctx)
                    direction = "bidirectional" if normalized.is_symmetric else "unidirectional"
                except Exception as exc:
                    log.warning("relation_normalization_failed", error=str(exc))

            source_id = entity_name_to_id.get(source_name)
            target_id = entity_name_to_id.get(target_name)

            if not source_id or not target_id:
                log.debug(
                    "entity_relation_entity_not_found",
                    source=source_name,
                    target=target_name,
                )
                continue

            try:
                await self._entity_repo.merge_relation(
                    from_neo4j_id=source_id,
                    to_neo4j_id=target_id,
                    edge_type=edge_type,
                    properties={
                        "raw_type": raw_type,
                        "direction": direction,
                        "description": relation.get("description"),
                    },
                )
                count += 1
                log.debug(
                    "entity_relation_created",
                    source=source_name,
                    target=target_name,
                    relation=edge_type,
                    raw_type=raw_type,
                )

                # TODO(temporary): Dual-write legacy RELATED_TO edges for backward
                # compatibility during migration.  Remove once all consumers have
                # been updated to read semantic edge types.  Controlled by
                # WEAVER_DUAL_WRITE=true environment variable.
                if os.environ.get("WEAVER_DUAL_WRITE", "").lower() == "true":
                    try:
                        await self._entity_repo.merge_relation(
                            from_neo4j_id=source_id,
                            to_neo4j_id=target_id,
                            edge_type="RELATED_TO",
                            properties={
                                "relation_type": raw_type,
                                "description": relation.get("description"),
                            },
                        )
                    except Exception as dual_exc:
                        log.debug("dual_write_failed", error=str(dual_exc))
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                log.error(
                    "entity_relation_failed",
                    source=source_name,
                    target=target_name,
                    relation=edge_type,
                    error=error_msg,
                    error_type=type(exc).__name__,
                )

        if count > 0:
            log.info("entity_relations_created", count=count)
        return count

    async def _resolve_canonical_name(
        self,
        name: str,
        entity_type: str,
    ) -> str:
        """Resolve canonical name for an entity.

        Looks up existing entities by vector similarity and determines
        the canonical name based on existing entries.

        Args:
            name: The entity name to resolve.
            entity_type: The entity type.

        Returns:
            The canonical name to use.
        """
        # First check if entity already exists
        existing = await self._entity_repo.find_entity(name, entity_type)
        if existing:
            return existing["canonical_name"]

        # For new entities, return the provided name as canonical
        # In a more sophisticated implementation, this could use
        # vector similarity to find existing entities and determine
        # the canonical name based on rules from neo4j-detail.md
        return name

    async def _create_followed_relations(
        self,
        article_id: str,
        source_ids: list[str],
        publish_time: datetime | None,
    ) -> None:
        """Create FOLLOWED_BY relationships for merged articles.

        When articles are merged, creates relationships indicating
        that the current article follows the source articles.

        Args:
            article_id: The target article's PostgreSQL ID.
            source_ids: List of source article PostgreSQL IDs that were merged.
            publish_time: Publication time of the target article.
        """
        for source_id in source_ids:
            try:
                # Calculate time gap if we have publish times
                time_gap: float | None = None

                # Get source article to calculate time gap
                source_article = await self._article_repo.find_article_by_pg_id(source_id)
                if source_article and publish_time and source_article.get("publish_time"):
                    source_time = source_article["publish_time"]
                    if hasattr(source_time, "timestamp") and hasattr(publish_time, "timestamp"):
                        time_gap = abs((publish_time.timestamp() - source_time.timestamp()) / 3600)

                await self._article_repo.create_followed_by_relation(
                    from_pg_id=source_id,
                    to_pg_id=article_id,
                    time_gap_hours=time_gap,
                )
                log.debug(
                    "neo4j_followed_by_created",
                    from_id=source_id,
                    to_id=article_id,
                )
            except Exception as exc:
                log.error(
                    "neo4j_followed_by_failed",
                    source_id=source_id,
                    target_id=article_id,
                    error=str(exc),
                )

    async def cleanup_orphan_entities(self) -> int:
        """Clean up orphan entities with no MENTIONS relationships.

        Returns:
            Number of entities deleted.
        """
        return await self._entity_repo.delete_orphan_entities()

    async def archive_old_articles(self, days: int = 90) -> int:
        """Archive old articles as part of data lifecycle management.

        Args:
            days: Number of days to retain articles.

        Returns:
            Number of articles deleted.
        """
        count = await self._article_repo.delete_old_articles(days)
        # After deleting articles, clean up orphan entities
        await self.cleanup_orphan_entities()
        return count
