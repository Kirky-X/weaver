# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Maintenance jobs for scheduler: cleanup and archival.

Responsibilities:
- Archive old Neo4j article nodes and orphan entities
- Clean up orphan entity vectors in PostgreSQL
- Clean up old synced pending records
- Clean up expired LLM failure and raw usage records
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from config.settings import SchedulerSettings
from core.observability import get_logger
from modules.knowledge.graph.neo4j_writer import Neo4jWriter
from modules.scheduler.wrapper import scheduled_task
from modules.storage import PendingSyncRepo, VectorRepo

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)

# Retention period for graph Article nodes. After the Article node
# slim-down (design.md §D2), the graph node no longer carries
# ``publish_time``; the cutoff is computed in Python (UTC now minus this
# many days) and the resulting cutoff datetime is sent as a bind param
# to keep the query portable across PostgreSQL and DuckDB.
ARCHIVE_RETENTION_DAYS = 90

# Page size for streaming cutoff pg_ids out of PostgreSQL. Loading all
# stale article IDs into memory at once can OOM on large archives
# (LOW-1 perf fix from T050 review). 1000 is small enough to keep peak
# memory bounded (~80KB per batch of UUID strings) yet large enough to
# avoid excessive round-trips on a 90-day retention window.
ARCHIVE_BATCH_SIZE = 1000


class MaintenanceJobs:
    """Scheduler jobs for routine maintenance: cleanup and archival.

    Handles archival of stale graph nodes, cleanup of orphan vectors and
    synced records, and retention-based cleanup of LLM failure and usage data.
    """

    def __init__(
        self,
        relational_pool: RelationalPool,
        graph_writer: Neo4jWriter,
        pending_sync_repo: PendingSyncRepo,
        vector_repo: VectorRepo | None = None,
        llm_failure_repo: Any = None,
        settings: SchedulerSettings | None = None,
    ) -> None:
        self._relational_pool = relational_pool
        self._graph_writer = graph_writer
        self._pending_sync_repo = pending_sync_repo
        # REM-001: vector_repo must be injected (constructing VectorRepo(pool)
        # fails with TypeError because query_builder is a required arg).
        self._vector_repo = vector_repo
        self._llm_failure_repo = llm_failure_repo
        self._settings = settings or SchedulerSettings()

    @scheduled_task("archive_old_neo4j_nodes", timeout_seconds=600)
    async def archive_old_neo4j_nodes(self) -> int:
        """Archive old Neo4j article nodes.

        Deletes Article nodes whose ``publish_time`` is older than
        ``ARCHIVE_RETENTION_DAYS`` days. After the Article node slim-down
        (design.md §D2), the graph node no longer carries ``publish_time``,
        so the cutoff pg_ids must be fetched from PostgreSQL first and
        then passed to the writer.

        Streaming (LOW-1 perf fix from T050 review):
            Previously this method loaded all cutoff pg_ids into memory at
            once and passed the full list to a single Cypher query. For
            large archives this can OOM. Now pg_ids are streamed in batches
            of ``ARCHIVE_BATCH_SIZE`` (1000) using keyset pagination
            (``WHERE id > :last_id ORDER BY id LIMIT :batch_size``) with
            ``last_id`` tracked across batches. Each batch is archived via
            a separate ``archive_old_articles`` call. Per-batch failures
            are logged and the loop continues (best-effort) so a transient
            error on one batch does not skip the remaining batches.
            ``cleanup_orphan_entities`` runs once at the end regardless of
            per-batch outcomes.

        Keyset vs OFFSET (MEDIUM-2 fix from T051 review):
            LIMIT/OFFSET scans+discards rows for high offsets (O(N²) for
            N batches) and is vulnerable to row drift when
            ``articles_core`` is mutated by concurrent ``deduplicate_articles``
            or backfill inserts. Keyset pagination on ``id`` (UUID string
            sort, stable across queries) is immune to drift: rows that
            sort before ``last_id`` are never re-fetched (no duplicates),
            and rows that sort after ``last_id`` are always fetched (no
            skips). The ``id`` column is UUID in PostgreSQL / VARCHAR in
            DuckDB — both sort lexicographically by string representation.

        Returns:
            Total number of articles archived across all batches.
        """
        log.info("archive_old_neo4j_nodes_start")

        try:
            from sqlalchemy import text

            # Compute the cutoff datetime in Python so the bind param is
            # portable across PostgreSQL and DuckDB (which have different
            # INTERVAL literal syntaxes). Use UTC for consistent behaviour
            # regardless of host timezone (articles_core.publish_time is
            # stored timezone-aware UTC).
            cutoff = datetime.now(UTC) - timedelta(days=ARCHIVE_RETENTION_DAYS)

            total_archived = 0
            total_seen = 0
            batch_num = 0
            had_batch_failure = False
            # Keyset cursor: None on first batch, then the last id fetched
            # in the previous batch. Tracked across batches so the next
            # query resumes strictly AFTER the previous batch's last id.
            last_id: str | None = None

            # Stream pg_ids via keyset pagination. Underlying articles_core
            # rows are not deleted here (only Article *graph* nodes are),
            # but concurrent inserts/deletes on articles_core can shift
            # OFFSET windows — keyset on ``id`` is immune to that drift.
            while True:
                batch_num += 1
                async with self._relational_pool.session() as session:
                    result = await session.execute(
                        text(
                            "SELECT id FROM articles_core "
                            "WHERE publish_time < :cutoff "
                            "AND (:last_id IS NULL OR id > :last_id) "
                            "ORDER BY id "
                            "LIMIT :limit"
                        ),
                        {
                            "cutoff": cutoff,
                            "last_id": last_id,
                            "limit": ARCHIVE_BATCH_SIZE,
                        },
                    )
                    batch_ids = [str(row[0]) for row in result]

                if not batch_ids:
                    # Empty result signals end of stream.
                    break

                total_seen += len(batch_ids)

                # Advance the keyset cursor BEFORE the per-batch archive
                # attempt — even if the archive call raises, the cursor
                # must move forward so the next batch is fetched (Rule 12:
                # a failed batch must not cause an infinite loop on the
                # same rows).
                last_id = batch_ids[-1]

                # Per-batch try/except: a single batch failure must NOT
                # abort the whole job (Rule 12 + Rule 24 — cover partial-
                # failure scenario). Log + continue so remaining batches
                # still get archived.
                try:
                    count = await self._graph_writer.archive_old_articles(batch_ids)
                    total_archived += count
                except Exception as batch_exc:
                    had_batch_failure = True
                    log.warning(
                        "archive_old_neo4j_nodes_batch_failed",
                        batch_num=batch_num,
                        batch_size=len(batch_ids),
                        error=str(batch_exc),
                    )

                # If batch was smaller than the page size, this was the
                # last batch — stop after cleanup.
                if len(batch_ids) < ARCHIVE_BATCH_SIZE:
                    break

            if total_seen == 0:
                log.info("archive_old_neo4j_nodes_complete", count=0, reason="no_old_articles")
                return 0

            # Orphan cleanup runs once after all batches — Law of Demeter:
            # invoke the writer's public cleanup method rather than reaching
            # through to entity_repo. LSP-aligned with LadybugWriter which
            # exposes the same cleanup_orphan_entities surface (both
            # writers uniformly orchestrate orphan cleanup via the caller,
            # MaintenanceJobs).
            try:
                await self._graph_writer.cleanup_orphan_entities()
            except Exception as cleanup_exc:
                # Cleanup failure is non-fatal to the archive count — log
                # and surface via the had_batch_failure flag.
                had_batch_failure = True
                log.warning(
                    "archive_old_neo4j_nodes_cleanup_failed",
                    error=str(cleanup_exc),
                )

            log.info(
                "archive_old_neo4j_nodes_complete",
                count=total_archived,
                cutoff_count=total_seen,
                batches=batch_num,
                had_batch_failure=had_batch_failure,
            )
            return total_archived
        except Exception as exc:
            log.error("archive_old_neo4j_nodes_failed", error=str(exc))
            return 0

    @scheduled_task("cleanup_orphan_entity_vectors", timeout_seconds=600)
    async def cleanup_orphan_entity_vectors(self) -> int:
        """Clean up orphan entity vectors.

        Removes entity vectors in Postgres/DuckDB that no longer have
        corresponding entities in the graph store (Neo4j/LadybugDB).

        REM-001 root cause fixes:
        - entity_vectors.neo4j_id stores a MIX of entity names (from
          entity_extractor path) and graph internal IDs (from entity_resolver
          path). Use UNION of list_all_entity_ids() and list_all_entity_names()
          to avoid false-positive orphan detection on either ID type.
        - Use injected self._vector_repo instead of constructing VectorRepo(pool)
          (which failed with TypeError due to missing query_builder arg).

        Returns:
            Number of vectors cleaned up.
        """
        log.info("cleanup_orphan_entity_vectors_start")

        if not self._vector_repo:
            log.error("cleanup_orphan_entity_vectors_failed", error="vector_repo not configured")
            return 0

        try:
            # REM-001: entity_vectors.neo4j_id stores mixed IDs (names + graph IDs).
            # Use union of both ID types to avoid false-positive orphan detection.
            active_ids = await self._graph_writer.entity_repo.list_all_entity_ids()
            active_names = await self._graph_writer.entity_repo.list_all_entity_names()
            active_keys = active_ids | active_names

            from sqlalchemy import text

            async with self._relational_pool.session() as session:
                result = await session.execute(text("SELECT neo4j_id FROM entity_vectors"))
                pg_keys = {row[0] for row in result}

            orphan_keys = pg_keys - active_keys

            if orphan_keys:
                count = await self._vector_repo.delete_entity_vectors_by_neo4j_ids(
                    list(orphan_keys)
                )
                log.info(
                    "cleanup_orphan_entity_vectors_complete",
                    count=count,
                    orphan_keys=list(orphan_keys)[:10],  # log first 10 for debugging
                )
                return count

            log.info("cleanup_orphan_entity_vectors_complete", count=0)
            return 0
        except Exception as exc:
            log.error("cleanup_orphan_entity_vectors_failed", error=str(exc))
            return 0

    @scheduled_task("cleanup_old_synced", timeout_seconds=300)
    async def cleanup_old_synced(self) -> int:
        """Clean up synced records older than 7 days.

        Returns:
            Number of records deleted.
        """
        log.info("cleanup_old_synced_start")

        try:
            deleted = await self._pending_sync_repo.cleanup_old_synced(days=7)
            log.info("cleanup_old_synced_complete", deleted=deleted)
            return deleted
        except Exception as exc:
            log.error("cleanup_old_synced_failed", error=str(exc))
            return 0

    @scheduled_task("llm_failure_cleanup", timeout_seconds=300)
    async def llm_failure_cleanup(self) -> int:
        """Clean up LLM failure records older than retention days."""
        if not self._llm_failure_repo:
            return 0
        deleted = await self._llm_failure_repo.cleanup_older_than(
            self._settings.llm_failure_cleanup_retention_days
        )
        return deleted

    @scheduled_task("llm_usage_raw_cleanup", timeout_seconds=300)
    async def llm_usage_raw_cleanup(self) -> int:
        """Clean up old raw LLM usage records."""
        from modules.analytics.llm_usage.repo import LLMUsageRepo

        repo = LLMUsageRepo(self._relational_pool)
        deleted = await repo.cleanup_raw_older_than(self._settings.llm_usage_raw_retention_days)
        return deleted
