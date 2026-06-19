# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Maintenance jobs for scheduler: cleanup and archival.

Responsibilities:
- Archive old Neo4j article nodes and orphan entities
- Clean up orphan entity vectors in PostgreSQL
- Clean up old synced pending records
- Clean up expired LLM failure and raw usage records
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.settings import SchedulerSettings
from core.observability import get_logger
from modules.knowledge.graph.neo4j_writer import Neo4jWriter
from modules.scheduler.wrapper import scheduled_task
from modules.storage import PendingSyncRepo, VectorRepo

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)


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
        llm_failure_repo: Any = None,
        settings: SchedulerSettings | None = None,
    ) -> None:
        self._relational_pool = relational_pool
        self._graph_writer = graph_writer
        self._pending_sync_repo = pending_sync_repo
        self._llm_failure_repo = llm_failure_repo
        self._settings = settings or SchedulerSettings()

    @scheduled_task("archive_old_neo4j_nodes", timeout_seconds=600)
    async def archive_old_neo4j_nodes(self) -> int:
        """Archive old Neo4j article nodes.

        Deletes Article nodes older than 90 days that have no
        FOLLOWED_BY relationships. Also cleans up orphan entities.

        Returns:
            Number of articles archived.
        """
        log.info("archive_old_neo4j_nodes_start")

        try:
            count = await self._graph_writer.archive_old_articles(days=90)
            await self._graph_writer.entity_repo.delete_orphan_entities()
            log.info("archive_old_neo4j_nodes_complete", count=count)
            return count
        except Exception as exc:
            log.error("archive_old_neo4j_nodes_failed", error=str(exc))
            return 0

    @scheduled_task("cleanup_orphan_entity_vectors", timeout_seconds=600)
    async def cleanup_orphan_entity_vectors(self) -> int:
        """Clean up orphan entity vectors.

        Removes entity vectors in Postgres that no longer have
        corresponding entities in Neo4j.

        Returns:
            Number of vectors cleaned up.
        """
        log.info("cleanup_orphan_entity_vectors_start")

        try:
            active_ids = await self._graph_writer.entity_repo.list_all_entity_ids()

            vector_repo = VectorRepo(self._relational_pool)

            from sqlalchemy import text

            async with self._relational_pool.session() as session:
                result = await session.execute(text("SELECT neo4j_id FROM entity_vectors"))
                pg_ids = {row[0] for row in result}

            orphan_ids = pg_ids - active_ids

            if orphan_ids:
                count = await vector_repo.delete_entity_vectors_by_neo4j_ids(list(orphan_ids))
                log.info("cleanup_orphan_entity_vectors_complete", count=count)
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
