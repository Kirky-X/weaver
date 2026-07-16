# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""LadybugDB writer for graph operations.

Coordinates entity and article repositories for graph write operations.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from core.db import PersistStatus
from core.observability import get_logger
from modules.storage.ladybug.article_repo import LadybugArticleRepo
from modules.storage.ladybug.entity_repo import LadybugEntityRepo

log = get_logger(__name__)

# Global write lock for LadybugDB (only one write transaction at a time)
_write_lock = asyncio.Lock()


class LadybugWriter:
    """LadybugDB graph writer.

    Coordinates entity and article operations for the knowledge graph.
    Similar to Neo4jWriter but adapted for LadybugDB.

    Note: LadybugDB only supports one write transaction at a time.
    All write operations are serialized via a global lock.

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

    @property
    def done_status(self) -> PersistStatus:
        """Return the PersistStatus for completed LadybugDB writes."""
        return PersistStatus.LADYBUG_DONE

    async def write(self, state: Any) -> list[str]:
        """Write pipeline state to the graph.

        Creates articles, entities, and their relationships.

        Note: Uses global write lock because LadybugDB only supports
        one write transaction at a time.

        Args:
            state: PipelineState containing article and entity data.

        Returns:
            List of created entity IDs.
        """
        # LadybugDB requires serialized write transactions
        async with _write_lock:
            return await self._write_locked(state)

    async def _write_locked(self, state: Any) -> list[str]:
        """Internal write implementation (must be called with lock held)."""
        entity_ids = []

        # Get article info - use dict access like Neo4jWriter
        article_id = state.get("article_id")
        if not article_id:
            log.warning("ladybug_write_missing_article_id")
            return entity_ids

        article_id = str(article_id)
        raw = state.get("raw")
        title = state.get("cleaned", {}).get("title", getattr(raw, "title", "") if raw else "")
        category = state.get("category", "未分类")
        category_str = category.value if hasattr(category, "value") else str(category)
        raw_publish_time = getattr(raw, "publish_time", None) if raw else None
        publish_time = int(raw_publish_time.timestamp()) if raw_publish_time else None
        score = state.get("score")

        # Create article node
        await self.article_repo.create_article(
            article_id=article_id,
            title=title,
            category=category_str,
            publish_time=publish_time,
            score=score,
        )

        # Create EventNode linked to Article
        body = state.get("cleaned", {}).get("body", "")
        event_content = f"{title}\n\n{body}" if body else title
        event_attributes = {"category": category_str}
        if score is not None:
            event_attributes["score"] = float(score)

        await self._pool.execute_query(
            """
            MERGE (e:EventNode {id: $id})
            SET e.content = $content,
                e.attributes = $attributes,
                e.event_type = $event_type,
                e.name = $name,
                e.event_time = $event_time,
                e.created_at = $created_at
            """,
            {
                "id": article_id,
                "content": event_content,
                "attributes": json.dumps(event_attributes, ensure_ascii=False),
                "event_type": "news",
                "name": title,
                # publish_time 为 None 时用当前时间, 避免 epoch 0 脏数据
                # (历史 bug: publish_time or 0 写入 0, 破坏 temporal 时间窗口过滤)
                "event_time": publish_time or int(time.time()),
                "created_at": int(time.time()),
            },
        )

        # Create HAS_EVENT relationship: Article → EventNode
        await self._pool.execute_query(
            """
            MATCH (a:Article {pg_id: $pg_id})
            MATCH (e:EventNode {id: $event_id})
            MERGE (a)-[:HAS_EVENT]->(e)
            """,
            {"pg_id": article_id, "event_id": article_id},
        )

        # Create entities and MENTIONS relationships
        entities = state.get("entities", [])
        entity_name_to_id: dict[str, str] = {}  # Build mapping during entity creation
        if entities:
            for entity in entities:
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
                entity_name_to_id[entity_name] = entity_id  # Store for later relation lookup

                # Create MENTIONS relationship
                await self.entity_repo.merge_mentions_relation(
                    article_id=article_id,
                    entity_id=entity_id,
                    role=role,
                )

        # Create FOLLOWED_BY relationships for article sequence
        related_articles = state.get("related_articles", [])
        if related_articles:
            for related in related_articles:
                related_pg_id = str(related.get("id", ""))
                time_gap = related.get("time_gap_hours")
                if related_pg_id:
                    await self.article_repo.create_followed_by_relation(
                        from_article_id=article_id,
                        to_article_id=related_pg_id,
                        time_gap_hours=time_gap,
                    )

        # Create entity relationships
        # Format: {"source": "name", "target": "name", "relation_type": "..."}
        relations = state.get("relations", [])
        log.debug(
            "ladybug_write_relations_check",
            article_id=article_id,
            relations_count=len(relations),
            relations=relations[:3] if relations else [],  # Log first 3 for debugging
        )
        if relations:
            for rel in relations:
                try:
                    source_name = rel.get("source")
                    target_name = rel.get("target")
                    edge_type = rel.get("relation_type", "RELATED_TO")
                    description = rel.get("description")

                    if not source_name or not target_name:
                        continue

                    # Find entity IDs
                    source_id = entity_name_to_id.get(source_name)
                    target_id = entity_name_to_id.get(target_name)

                    log.debug(
                        "ladybug_relation_lookup",
                        source_name=source_name,
                        target_name=target_name,
                        source_id=source_id,
                        target_id=target_id,
                        entity_name_to_id_keys=list(entity_name_to_id.keys())[:5],
                    )

                    # If not in cache, look up in database or create if not exists
                    if not source_id:
                        source_ent = await self.entity_repo.find_entity_by_name(source_name)
                        if source_ent:
                            source_id = source_ent["id"]
                            entity_name_to_id[source_name] = source_id
                        else:
                            # Entity not found - create it (ensure existence for relation)
                            source_id = await self.entity_repo.merge_entity(
                                canonical_name=source_name,
                                entity_type="未知",  # Default type for inferred entities
                                description=None,
                                tier=3,  # Lower tier for auto-created entities
                            )
                            entity_name_to_id[source_name] = source_id
                            log.debug(
                                "ladybug_entity_auto_created",
                                name=source_name,
                                entity_id=source_id,
                                reason="relation_source_not_found",
                            )

                    if not target_id:
                        target_ent = await self.entity_repo.find_entity_by_name(target_name)
                        if target_ent:
                            target_id = target_ent["id"]
                            entity_name_to_id[target_name] = target_id
                        else:
                            # Entity not found - create it (ensure existence for relation)
                            target_id = await self.entity_repo.merge_entity(
                                canonical_name=target_name,
                                entity_type="未知",  # Default type for inferred entities
                                description=None,
                                tier=3,  # Lower tier for auto-created entities
                            )
                            entity_name_to_id[target_name] = target_id
                            log.debug(
                                "ladybug_entity_auto_created",
                                name=target_name,
                                entity_id=target_id,
                                reason="relation_target_not_found",
                            )

                    # Normalize edge type
                    if self._relation_type_normalizer:
                        try:
                            normalized = await self._relation_type_normalizer.normalize(edge_type)
                            edge_type = normalized.name_en or edge_type
                        except Exception as exc:
                            log.warning("relation_normalization_failed", error=str(exc))

                    await self.entity_repo.merge_relation(
                        from_entity_id=source_id,
                        to_entity_id=target_id,
                        edge_type=edge_type,
                        properties={"description": description} if description else {},
                    )
                    log.debug(
                        "ladybug_relation_created",
                        source_id=source_id,
                        target_id=target_id,
                        edge_type=edge_type,
                    )
                except Exception as exc:
                    log.error(
                        "ladybug_relation_loop_error",
                        error=str(exc),
                    )

        return entity_ids

    async def write_batch(
        self,
        states: list[Any],
        concurrency: int = 1,  # LadybugDB only supports 1 writer at a time
    ) -> dict[str, Any]:
        """Write multiple pipeline states to LadybugDB.

        Note: LadybugDB only supports one write transaction at a time,
        so we serialize all writes using the global lock.

        Args:
            states: List of pipeline states to persist.
            concurrency: Ignored (LadybugDB is single-writer).

        Returns:
            Dict with:
            - neo4j_ids: List of per-article entity ID lists (list[list[str]]).
              neo4j_ids[i] contains the entity IDs for the i-th input state.
            - article_ids: List of article IDs successfully written.
            - errors: List of (article_id, error_msg) for failures.
        """
        if not states:
            return {"neo4j_ids": [], "article_ids": [], "errors": []}

        result: dict[str, Any] = {
            "neo4j_ids": [],
            "article_ids": [],
            "errors": [],
        }

        # LadybugDB only supports serialized writes
        for state in states:
            try:
                async with _write_lock:
                    ids = await self._write_locked(state)
                    article_id = str(state.get("article_id", "unknown"))
                    result["neo4j_ids"].append(ids)
                    result["article_ids"].append(article_id)
            except Exception as exc:
                article_id = str(state.get("article_id", "unknown"))
                error_msg = f"{type(exc).__name__}: {exc}"
                log.error(
                    "ladybug_batch_write_failed",
                    article_id=article_id,
                    error=error_msg,
                )
                result["neo4j_ids"].append([])
                result["errors"].append((article_id, error_msg))

        log.info(
            "ladybug_batch_write_complete",
            total=len(states),
            success=len(result["article_ids"]),
            failed=len(result["errors"]),
        )
        return result

    async def cleanup_orphan_entities(self) -> int:
        """Remove entities with no relationships."""
        return await self.entity_repo.delete_orphan_entities()

    async def archive_old_articles(self, days: int = 90) -> int:
        """Archive/delete articles older than specified days."""
        return await self.article_repo.delete_old_articles(days)
