# Copyright (c) 2026 KirkyX. All Rights Reserved
"""LadybugDB writer for graph operations.

Coordinates entity and article repositories for graph write operations.
"""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger
from modules.storage.ladybug.article_repo import LadybugArticleRepo
from modules.storage.ladybug.entity_repo import LadybugEntityRepo

log = get_logger("ladybug_writer")


class LadybugWriter:
    """LadybugDB graph writer.

    Coordinates entity and article operations for the knowledge graph.
    Similar to Neo4jWriter but adapted for LadybugDB.

    Args:
        pool: LadybugPool instance.
        relation_type_normalizer: Optional normalizer for relation types.
    """

    def __init__(self, pool, relation_type_normalizer=None) -> None:
        self._pool = pool
        self._entity_repo: LadybugEntityRepo | None = None
        self._article_repo: LadybugArticleRepo | None = None
        self._relation_type_normalizer = relation_type_normalizer

    @property
    def entity_repo(self) -> LadybugEntityRepo:
        """Get entity repository."""
        if self._entity_repo is None:
            self._entity_repo = LadybugEntityRepo(self._pool)
        return self._entity_repo

    @property
    def article_repo(self) -> LadybugArticleRepo:
        """Get article repository."""
        if self._article_repo is None:
            self._article_repo = LadybugArticleRepo(self._pool)
        return self._article_repo

    async def ensure_constraints(self) -> None:
        """Create constraints/schema if needed.

        Schema is created during initialization in schema.py.
        """
        pass

    async def write(self, state: Any) -> list[str]:
        """Write pipeline state to the graph.

        Creates articles, entities, and their relationships.

        Args:
            state: PipelineState containing article and entity data.

        Returns:
            List of created entity IDs.
        """
        entity_ids = []

        # Get article info
        article_id = str(state.id)
        title = state.title or ""
        category = state.category or "未分类"
        publish_time = int(state.publish_time.timestamp()) if state.publish_time else None
        score = state.score

        # Create article node
        await self.article_repo.create_article(
            pg_id=article_id,
            title=title,
            category=category,
            publish_time=publish_time,
            score=score,
        )

        # Create entities and MENTIONS relationships
        if state.entities:
            for entity in state.entities:
                entity_name = entity.get("canonical_name") or entity.get("name", "")
                entity_type = entity.get("type", "未知")
                description = entity.get("description")
                tier = entity.get("tier", 2)
                role = entity.get("role")

                if not entity_name:
                    continue

                # Merge entity
                entity_id = await self.entity_repo.merge_entity(
                    canonical_name=entity_name,
                    entity_type=entity_type,
                    description=description,
                    tier=tier,
                )
                entity_ids.append(entity_id)

                # Create MENTIONS relationship
                await self.entity_repo.merge_mentions_relation(
                    article_id=article_id,
                    entity_id=entity_id,
                    role=role,
                )

        # Create FOLLOWED_BY relationships for article sequence
        if state.related_articles:
            for related in state.related_articles:
                related_pg_id = str(related.get("id", ""))
                time_gap = related.get("time_gap_hours")
                if related_pg_id:
                    await self.article_repo.create_followed_by_relation(
                        from_pg_id=article_id,
                        to_pg_id=related_pg_id,
                        time_gap_hours=time_gap,
                    )

        # Create entity relationships
        if state.relations:
            for rel in state.relations:
                from_entity = rel.get("from_entity", {})
                to_entity = rel.get("to_entity", {})
                edge_type = rel.get("relation_type", "RELATED_TO")
                properties = rel.get("properties", {})

                from_name = from_entity.get("canonical_name") or from_entity.get("name", "")
                from_type = from_entity.get("type", "未知")
                to_name = to_entity.get("canonical_name") or to_entity.get("name", "")
                to_type = to_entity.get("type", "未知")

                if not from_name or not to_name:
                    continue

                # Find entities
                from_ent = await self.entity_repo.find_entity(from_name, from_type)
                to_ent = await self.entity_repo.find_entity(to_name, to_type)

                if from_ent and to_ent:
                    # Normalize edge type
                    if self._relation_type_normalizer:
                        edge_type = self._relation_type_normalizer.normalize(edge_type)

                    await self.entity_repo.merge_relation(
                        from_entity_id=from_ent["id"],
                        to_entity_id=to_ent["id"],
                        edge_type=edge_type,
                        properties=properties,
                    )

        return entity_ids

    async def cleanup_orphan_entities(self) -> int:
        """Remove entities with no relationships."""
        return await self.entity_repo.delete_orphan_entities()

    async def archive_old_articles(self, days: int = 90) -> int:
        """Archive/delete articles older than specified days."""
        return await self.article_repo.delete_old_articles(days)
