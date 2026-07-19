# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Graph writer for persisting pipeline state to graph database."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from core.db import PersistStatus
from core.observability import get_logger
from core.types.pipeline_state import PipelineState
from modules.storage.neo4j.article_repo import Neo4jArticleRepo
from modules.storage.neo4j.entity_repo import Neo4jEntityRepo

if TYPE_CHECKING:
    from core.protocols import GraphPool
    from modules.knowledge.graph.relation_type_normalizer import RelationTypeNormalizer

log = get_logger(__name__)


class Neo4jWriter:
    """Writes pipeline processing results to graph database.

    Coordinates entity and article repositories to persist:
    - Article nodes with metadata
    - Entity nodes from extraction
    - MENTIONS relationships (article -> entity)
    - FOLLOWED_BY relationships (article -> article)
    - Typed entity-to-entity relationships (normalised via RelationTypeNormalizer)

    Implements: GraphWriteStrategy

    Args:
        pool: Graph database connection pool.
        relation_type_normalizer: Optional normaliser for relation types.
            When provided, LLM-extracted relation types are normalised
            before writing to graph database.
    """

    def __init__(
        self,
        pool: GraphPool,
        relation_type_normalizer: RelationTypeNormalizer | None = None,
        entity_repo: Neo4jEntityRepo | None = None,
        article_repo: Neo4jArticleRepo | None = None,
    ) -> None:
        self._pool = pool
        self._entity_repo = entity_repo or Neo4jEntityRepo(pool)
        self._article_repo = article_repo or Neo4jArticleRepo(pool)
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

    @property
    def done_status(self) -> PersistStatus:
        """Return the PersistStatus for completed Neo4j writes."""
        return PersistStatus.NEO4J_DONE

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

        # After the Article node slim-down (design.md §D2), the graph node
        # stores only {pg_id, created_at}. Title / category / publish_time /
        # score are no longer persisted on the node; callers that need them
        # batch-fetch from PostgreSQL via ArticleRepository.fetch_titles_by_pg_ids.
        article_neo4j_id = await self._article_repo.create_article(
            article_id=article_id_str,
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
            )

        log.info("neo4j_write_complete", article_id=article_id_str, entity_count=len(neo4j_ids))
        return neo4j_ids

    async def write_batch(
        self,
        states: list[PipelineState],
        concurrency: int = 10,
    ) -> dict[str, Any]:
        """Write multiple pipeline states to Neo4j with controlled concurrency.

        Uses asyncio.gather with semaphore for parallel execution.
        Each state is written independently, failures are recorded.

        Args:
            states: List of pipeline states to persist.
            concurrency: Maximum concurrent writes (default 10).

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

        semaphore = asyncio.Semaphore(concurrency)

        async def write_with_semaphore(
            state: PipelineState,
        ) -> tuple[list[str], str | None, str | None]:
            async with semaphore:
                try:
                    ids = await self.write(state)
                    article_id = str(state.get("article_id", "unknown"))
                    return ids, article_id, None
                except Exception as exc:
                    article_id = str(state.get("article_id", "unknown"))
                    error_msg = f"{type(exc).__name__}: {exc}"
                    log.error(
                        "neo4j_batch_write_failed",
                        article_id=article_id,
                        error=error_msg,
                    )
                    return [], article_id, error_msg

        write_results = await asyncio.gather(
            *[write_with_semaphore(s) for s in states],
            return_exceptions=False,
        )

        for ids, article_id, error in write_results:
            result["neo4j_ids"].append(ids)
            # REM-005: Only add to article_ids when there is no error.
            # Previously failed articles were added to both article_ids and
            # errors, causing double counting (batch_completed + batch_failed
            # both incremented for the same article). Aligns with
            # LadybugWriter.write_batch behavior.
            if error:
                result["errors"].append((article_id or "unknown", error))
            elif article_id:
                result["article_ids"].append(article_id)

        log.info(
            "neo4j_batch_write_complete",
            total=len(states),
            success=len(result["article_ids"]),
            failed=len(result["errors"]),
        )
        return result

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
        # Map original names (and aliases) to canonical names for relation resolution
        original_to_canonical: dict[str, str] = {}

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

            # Build mapping from original name to canonical name
            original_to_canonical[name] = canonical_name

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

        # Batch query to get entity IDs instead of N+1 individual queries
        entity_keys = [
            {"canonical_name": e["canonical_name"], "type": e["type"]} for e in entity_data
        ]
        existing_entities = await self._entity_repo.find_entities_by_keys(entity_keys)

        # Build lookup map for quick access
        existing_map = {(e.canonical_name, e.type): e.id for e in existing_entities}

        # Collect IDs and populate name_to_id map in same order as entity_data
        entity_ids: list[str] = []
        for entity in entity_data:
            key = (entity["canonical_name"], entity["type"])
            if key in existing_map:
                entity_ids.append(existing_map[key])
                entity_name_to_id[entity["canonical_name"]] = existing_map[key]

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
            await self._write_entity_relations(relations, entity_name_to_id, original_to_canonical)

        return entity_ids

    async def _write_entity_relations(
        self,
        relations: list[dict[str, Any]],
        entity_name_to_id: dict[str, str],
        original_to_canonical: dict[str, str] | None = None,
    ) -> int:
        """Write entity-to-entity relationships to Neo4j.

        When a ``RelationTypeNormalizer`` is available each LLM-extracted
        relation type is normalised before writing.  Unknown types are
        recorded for later review.

        Args:
            relations: List of relation dicts from entity extractor.
            entity_name_to_id: Mapping from entity canonical name to Neo4j ID.
            original_to_canonical: Mapping from original entity name to canonical name.

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

            # Resolve original names to canonical names before lookup
            source_canonical = (original_to_canonical or {}).get(source_name, source_name)
            target_canonical = (original_to_canonical or {}).get(target_name, target_name)

            source_id = entity_name_to_id.get(source_canonical)
            target_id = entity_name_to_id.get(target_canonical)

            if not source_id or not target_id:
                log.debug(
                    "entity_relation_entity_not_found",
                    source=source_name,
                    target=target_name,
                )
                continue

            try:
                await self._entity_repo.merge_relation(
                    from_entity_id=source_id,
                    to_entity_id=target_id,
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
            return existing.canonical_name

        # For new entities, return the provided name as canonical
        # In a more sophisticated implementation, this could use
        # vector similarity to find existing entities and determine
        # the canonical name based on rules from neo4j-detail.md
        return name

    async def _create_followed_relations(
        self,
        article_id: str,
        source_ids: list[str],
    ) -> None:
        """Create FOLLOWED_BY relationships for merged articles using batch operation.

        After the Article node slim-down (design.md §D2), the graph Article
        node no longer carries ``publish_time``, so ``time_gap_hours`` can
        no longer be computed inside the graph layer. The relation is
        created with ``time_gap_hours=0.0``; callers needing accurate time
        gaps should compute them from PostgreSQL ``publish_time`` at query
        time (consistent with LadybugWriter which reads
        ``state["related_articles"]`` for time gaps).

        P4 fix: replaced the per-source ``find_article_by_id`` loop with
        a single ``find_articles_by_pg_ids`` batch query to avoid N+1
        round-trips on the pipeline write hot path. Missing sources are
        still logged as warnings so operators can spot dangling merges.

        Args:
            article_id: The target article's PostgreSQL ID.
            source_ids: List of source article PostgreSQL IDs that were merged.
        """
        if not source_ids:
            return

        # Single round-trip: fetch existence for all source_ids at once.
        try:
            existing_map = await self._article_repo.find_articles_by_pg_ids(source_ids)
        except Exception as exc:
            log.warning(
                "neo4j_followed_by_batch_lookup_failed",
                to_id=article_id,
                error=str(exc),
            )
            return

        relations_data: list[dict[str, Any]] = []
        for source_id in source_ids:
            if source_id not in existing_map:
                log.warning(
                    "neo4j_followed_by_source_missing",
                    source_id=source_id,
                )
                continue
            relations_data.append(
                {
                    "from_pg_id": source_id,
                    "to_pg_id": article_id,
                    "time_gap_hours": 0.0,
                }
            )

        # Only create relations if we have valid data
        if not relations_data:
            return

        try:
            count = await self._article_repo.create_followed_by_batch(relations_data)
            log.info(
                "neo4j_followed_by_batch_created",
                count=count,
                from_ids=source_ids,
                to_id=article_id,
            )
        except Exception as exc:
            log.error(
                "neo4j_followed_by_batch_failed",
                from_ids=source_ids,
                to_id=article_id,
                error=str(exc),
            )

    async def cleanup_orphan_entities(self) -> int:
        """Clean up orphan entities with no MENTIONS relationships.

        Returns:
            Number of entities deleted.
        """
        return await self._entity_repo.delete_orphan_entities()

    async def archive_old_articles(self, cutoff_pg_ids: list[str]) -> int:
        """Archive old articles as part of data lifecycle management.

        After the Article node slim-down (design.md §D2), the graph node no
        longer carries ``publish_time``, so the caller must compute the
        cutoff by querying PostgreSQL for
        ``publish_time < NOW() - INTERVAL '$days days'`` and pass the
        resulting pg_ids here.

        LSP alignment: this method only deletes Article nodes. The caller
        (MaintenanceJobs.archive_old_neo4j_nodes) is responsible for
        invoking ``cleanup_orphan_entities()`` afterwards. Previously this
        method called cleanup_orphan_entities() when cutoff_pg_ids was
        non-empty, but LadybugWriter.archive_old_articles did not —
        causing an LSP violation where two interchangeable Writer
        implementations had different side effects. Cleanup is now
        uniformly orchestrated by the caller.

        Args:
            cutoff_pg_ids: List of pg_ids to delete. Empty list is a no-op.

        Returns:
            Number of articles deleted.
        """
        return await self._article_repo.delete_old_articles(cutoff_pg_ids)

    async def merge_narrative(
        self,
        article_id: str,
        source_bias: str,
        frame: str,
        tone: str,
        emphasis: str,
    ) -> str:
        """Merge a NarrativeNode and link it to the article's EventNode.

        Implements: GraphWriter.merge_narrative

        Creates or updates a NarrativeNode with the four framing dimensions
        (source_bias/frame/tone/emphasis), then establishes
        EventNode-[:HAS_NARRATIVE]->NarrativeNode relationship.

        EventNode is idempotently MERGEd inside this call (id = article_id)
        to avoid pipeline phase ordering coupling: the caller does not need
        to guarantee EventNode pre-existence. If EventNode was already
        created by memory_publisher or LadybugWriter.write, MERGE is a no-op;
        otherwise this call creates a minimal EventNode stub.

        Args:
            article_id: Article UUID string. Used as EventNode id and to
                derive NarrativeNode id.
            source_bias: 媒体立场倾向.
            frame: 叙事框架.
            tone: 文章语调.
            emphasis: 报道侧重点.

        Returns:
            The NarrativeNode business-level ID (format: "narrative-{article_id}"),
            stable across re-runs and consistent across Neo4j/Ladybug backends.
        """
        narrative_id = f"narrative-{article_id}"
        query = """
        MERGE (n:NarrativeNode {id: $narrative_id})
        SET n.source_bias = $source_bias,
            n.frame = $frame,
            n.tone = $tone,
            n.emphasis = $emphasis,
            n.updated_at = timestamp()
        WITH n
        MERGE (e:EventNode {id: $article_id})
        MERGE (e)-[:HAS_NARRATIVE]->(n)
        RETURN n.id AS narrative_id
        """
        result = await self._pool.execute_query(
            query,
            {
                "narrative_id": narrative_id,
                "article_id": article_id,
                "source_bias": source_bias,
                "frame": frame,
                "tone": tone,
                "emphasis": emphasis,
            },
        )
        records = result or []
        if not records:
            raise RuntimeError(f"merge_narrative returned no records for article_id={article_id}")
        record = records[0]
        if hasattr(record, "get"):
            returned_id = record.get("narrative_id") or record.get(0)
        else:
            returned_id = record[0] if record else None
        if not returned_id:
            raise RuntimeError(
                f"merge_narrative: NarrativeNode id empty for article_id={article_id}"
            )
        return str(returned_id)

    async def merge_schema(
        self,
        event_type: str,
        pattern: str,
        confidence: float,
    ) -> str:
        """Merge a SchemaNode keyed by event_type (no relationships).

        Implements: GraphWriter.merge_schema

        Creates or updates a SchemaNode with the event pattern (JSON Schema
        string) and confidence. SchemaNode is MERGEd by event_type so that
        multiple articles reporting the same event type collapse into one
        SchemaNode (idempotent upsert). No relationships are created —
        SchemaNode serves as a standalone schema registry.

        Confidence-based update policy: on MATCH, pattern/confidence are only
        updated when the new confidence is strictly greater than the stored
        value. This prevents a low-confidence extraction from overwriting a
        high-quality pattern from a previous article. updated_at is always
        refreshed to reflect the last attempt.

        A deterministic id ("schema-{event_type}") is assigned on create so
        the business-level ID is stable across re-runs and consistent with
        LadybugWriter (LSP requirement).

        Args:
            event_type: Event type string (e.g. 融资/政策发布).
            pattern: JSON Schema string describing the event's fields.
            confidence: LLM confidence score [0.0, 1.0].

        Returns:
            The SchemaNode business-level ID (format: "schema-{event_type}").

        Raises:
            RuntimeError: If the query returns no records (unexpected failure).
        """
        schema_id = f"schema-{event_type}"
        query = """
        MERGE (s:SchemaNode {event_type: $event_type})
        ON CREATE SET s.id = $schema_id,
                      s.created_at = timestamp(),
                      s.pattern = $pattern,
                      s.confidence = $confidence
        ON MATCH SET s.pattern = CASE WHEN $confidence > s.confidence THEN $pattern ELSE s.pattern END,
                     s.confidence = CASE WHEN $confidence > s.confidence THEN $confidence ELSE s.confidence END
        SET s.updated_at = timestamp()
        RETURN s.id AS schema_id
        """
        result = await self._pool.execute_query(
            query,
            {
                "event_type": event_type,
                "schema_id": schema_id,
                "pattern": pattern,
                "confidence": confidence,
            },
        )
        records = result or []
        if not records:
            raise RuntimeError(f"merge_schema returned no records for event_type={event_type}")
        record = records[0]
        if hasattr(record, "get"):
            returned_id = record.get("schema_id") or record.get(0)
        else:
            returned_id = record[0] if record else None
        if not returned_id:
            raise RuntimeError(f"merge_schema: SchemaNode id empty for event_type={event_type}")
        return str(returned_id)
