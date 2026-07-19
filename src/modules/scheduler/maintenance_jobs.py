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

        Returns:
            Number of articles archived.
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

            async with self._relational_pool.session() as session:
                result = await session.execute(
                    text("SELECT id FROM articles_core WHERE publish_time < :cutoff"),
                    {"cutoff": cutoff},
                )
                cutoff_pg_ids = [str(row[0]) for row in result]

            if not cutoff_pg_ids:
                log.info("archive_old_neo4j_nodes_complete", count=0, reason="no_old_articles")
                return 0

            count = await self._graph_writer.archive_old_articles(cutoff_pg_ids)
            # Law of Demeter: invoke the writer's public cleanup method
            # rather than reaching through to entity_repo. LSP-aligned with
            # LadybugWriter which exposes the same cleanup_orphan_entities
            # surface (both writers uniformly orchestrate orphan cleanup
            # via the caller, MaintenanceJobs).
            await self._graph_writer.cleanup_orphan_entities()
            log.info(
                "archive_old_neo4j_nodes_complete",
                count=count,
                cutoff_count=len(cutoff_pg_ids),
            )
            return count
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
