"""Neo4j writer for persisting pipeline state to graph database."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.db.neo4j import Neo4jPool
from core.observability.logging import get_logger
from modules.storage.neo4j.article_repo import Neo4jArticleRepo
from modules.storage.neo4j.entity_repo import Neo4jEntityRepo
from modules.pipeline.state import PipelineState

log = get_logger("neo4j_writer")


class Neo4jWriter:
    """Writes pipeline processing results to Neo4j graph database.

    Coordinates entity and article repositories to persist:
    - Article nodes with metadata
    - Entity nodes from extraction
    - MENTIONS relationships (article -> entity)
    - FOLLOWED_BY relationships (article -> article)

    Args:
        pool: Neo4j connection pool.
    """

    def __init__(self, pool: Neo4jPool) -> None:
        self._pool = pool
        self._entity_repo = Neo4jEntityRepo(pool)
        self._article_repo = Neo4jArticleRepo(pool)

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
        """Write entities and create MENTIONS relationships.

        Args:
            article_neo4j_id: The article's Neo4j ID.
            entities: List of entity dicts from entity extractor.
            state: Pipeline state for additional context.

        Returns:
            List of entity Neo4j IDs.
        """
        entity_ids: list[str] = []
        language = state.get("language", "zh")
        entity_name_to_id: dict[str, str] = {}

        for entity in entities:
            name = entity.get("name")
            entity_type = entity.get("type")
            role = entity.get("role")

            if not name or not entity_type:
                continue

            canonical_name = await self._resolve_canonical_name(name, entity_type)

            try:
                entity_neo4j_id = await self._entity_repo.merge_entity(
                    canonical_name=canonical_name,
                    entity_type=entity_type,
                    description=entity.get("description"),
                )
                entity_ids.append(entity_neo4j_id)
                entity_name_to_id[canonical_name] = entity_neo4j_id

                if name != canonical_name:
                    await self._entity_repo.add_alias(
                        canonical_name=canonical_name,
                        entity_type=entity_type,
                        alias=name,
                    )

            except Exception as exc:
                log.error(
                    "neo4j_entity_merge_failed",
                    name=name,
                    type=entity_type,
                    error=str(exc),
                )
                continue

            try:
                await self._entity_repo.merge_mentions_relation(
                    article_neo4j_id=article_neo4j_id,
                    entity_neo4j_id=entity_neo4j_id,
                    role=role,
                )
            except Exception as exc:
                log.error(
                    "neo4j_mentions_relation_failed",
                    article_id=article_neo4j_id,
                    entity_id=entity_neo4j_id,
                    error=str(exc),
                )

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
            description = relation.get("description")

            if not source_name or not target_name or not relation_type:
                continue

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
                    relation_type=relation_type,
                    properties={"description": description} if description else None,
                )
                count += 1
                log.debug(
                    "entity_relation_created",
                    source=source_name,
                    target=target_name,
                    relation=relation_type,
                )
            except Exception as exc:
                log.error(
                    "entity_relation_failed",
                    source=source_name,
                    target=target_name,
                    relation=relation_type,
                    error=str(exc),
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
                        time_gap = abs(
                            (publish_time.timestamp() - source_time.timestamp()) / 3600
                        )

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
