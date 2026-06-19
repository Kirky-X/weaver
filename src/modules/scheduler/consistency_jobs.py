# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Consistency jobs for scheduler: retry, sync, and consistency checks.

Responsibilities:
- Retry failed Neo4j writes and pipeline processing
- Flush expired crawl retry queue items
- Synchronize Neo4j with PostgreSQL
- Detect and report consistency issues between graph and relational stores
"""

from __future__ import annotations

import asyncio
import collections
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import json_repair
from sqlalchemy import and_, select

from config.settings import SchedulerSettings
from core.db import Article, PersistStatus
from core.observability import get_logger
from core.observability.metrics import metrics
from modules.knowledge.graph.neo4j_writer import Neo4jWriter
from modules.scheduler.wrapper import scheduled_task
from modules.storage import ArticleRepo, PendingSyncRepo, VectorRepo

if TYPE_CHECKING:
    from core.protocols import CachePool, RelationalPool

log = get_logger(__name__)

MAX_BATCH_RETRIES = 10


class ConsistencyJobs:
    """Scheduler jobs for data consistency: retry, sync, and consistency checks.

    Handles retry of failed writes, synchronization between Neo4j and PostgreSQL,
    pipeline retry processing, and consistency diagnostics between graph and
    relational stores.
    """

    def __init__(
        self,
        relational_pool: RelationalPool,
        cache: CachePool,
        graph_writer: Neo4jWriter,
        vector_repo: VectorRepo,
        article_repo: ArticleRepo,
        pending_sync_repo: PendingSyncRepo,
        pipeline: Any = None,
        settings: SchedulerSettings | None = None,
    ) -> None:
        self._relational_pool = relational_pool
        self._cache = cache
        self._graph_writer = graph_writer
        self._vector_repo = vector_repo
        self._article_repo = article_repo
        self._pending_sync_repo = pending_sync_repo
        self._pipeline = pipeline
        self._settings = settings or SchedulerSettings()

    @scheduled_task("retry_neo4j_writes", timeout_seconds=300)
    async def retry_neo4j_writes(self) -> int:
        """Retry failed Neo4j writes.

        Scans for articles with persist_status='pg_done' that have been
        in that state for more than 10 minutes, then attempts to write
        to Neo4j again. Prefers pending_sync payload over _reconstruct_state.

        Returns:
            Number of articles retried.
        """
        log.info("retry_neo4j_writes_start")

        async with self._relational_pool.session() as session:
            # Find articles stuck in pg_done state for > 10 minutes
            threshold = datetime.now(UTC) - timedelta(minutes=10)

            stmt = (
                select(Article)
                .where(
                    and_(
                        Article.persist_status == PersistStatus.PG_DONE,
                        Article.updated_at < threshold,
                    )
                )
                .limit(self._settings.consistency_check_batch_size)
            )  # Process in batches

            result = await session.execute(stmt)
            articles = result.scalars().all()

            if not articles:
                log.info("retry_neo4j_writes_no_items")
                return 0

            retry_count = 0
            consecutive_failures = 0
            for article in articles:
                try:
                    # Prefer pending_sync payload over _reconstruct_state
                    pending_sync = await self._pending_sync_repo.get_by_article_id(article.id)
                    if pending_sync:
                        state = self._pending_sync_repo.reconstruct_state_from_payload(
                            pending_sync.payload
                        )
                        log.debug(
                            "retry_neo4j_using_pending_sync",
                            article_id=str(article.id),
                        )
                    else:
                        state = await self._reconstruct_state(article)
                        log.debug(
                            "retry_neo4j_using_reconstruct",
                            article_id=str(article.id),
                        )

                    # Attempt Neo4j write
                    await self._graph_writer.write(state)

                    # Update status
                    article.persist_status = self._graph_writer.done_status
                    await session.commit()
                    retry_count += 1
                    consecutive_failures = 0

                    log.debug("retry_neo4j_write_success", article_id=str(article.id))

                except Exception as exc:
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_BATCH_RETRIES:
                        log.warning(
                            "retry_neo4j_max_failures_reached",
                            failures=consecutive_failures,
                        )
                        break
                    log.error(
                        "retry_neo4j_write_failed",
                        article_id=str(article.id),
                        error=str(exc),
                    )
                    # Leave in pg_done state for next retry

            log.info("retry_neo4j_writes_complete", retry_count=retry_count)
            return retry_count

    @scheduled_task("flush_retry_queue", timeout_seconds=60)
    async def flush_retry_queue(self) -> int:
        """Flush expired retry queue items back to crawl queue.

        Processes crawl:retry:{host} sorted sets and re-queues
        items whose retry time has passed.

        Returns:
            Number of items requeued.
        """
        log.info("flush_retry_queue_start")

        # Get all host keys using scan_iter (non-blocking)
        keys_to_process = []
        async for key in self._cache.scan_iter("crawl:retry:*"):
            keys_to_process.append(key)

        if not keys_to_process:
            log.info("flush_retry_queue_no_keys")
            return 0

        requeue_count = 0
        now = datetime.now(UTC).timestamp()

        for key in keys_to_process:
            # Get items ready for retry
            # ZRANGEBYSCORE key -inf now
            items = await self._cache.zrangebyscore(key, "-inf", now)

            if items:
                # Remove from retry queue
                await self._cache.zrem(key, *items)

                # Add to crawl queue
                for item in items:
                    await self._cache.lpush("crawl:queue", item)
                    requeue_count += 1

        log.info("flush_retry_queue_complete", count=requeue_count)
        return requeue_count

    @scheduled_task("sync_neo4j_with_postgres", timeout_seconds=600)
    async def sync_neo4j_with_postgres(self) -> dict[str, Any]:
        """Synchronize Neo4j articles with PostgreSQL.

        Detects and cleans up three types of inconsistency:
        1. Orphan Neo4j nodes (in Neo4j but not in PostgreSQL)
        2. Enrichment gaps (NEO4J_DONE status but NULL enrichment fields)
        3. Entity count mismatch between Neo4j and PostgreSQL entity_vectors

        Returns:
            Dict with counts of orphans deleted, articles cleaned, and
            enrichment gaps detected/reverted.
        """
        log.info("sync_neo4j_with_postgres_start")

        try:
            pg_ids = await self._article_repo.get_all_article_ids()

            # 1. Detect and clean up orphan Neo4j nodes
            neo4j_ids = await self._graph_writer.article_repo.list_all_article_ids()
            orphan_ids = set(neo4j_ids) - pg_ids

            deleted = 0
            if orphan_ids:
                deleted = await self._graph_writer.article_repo.delete_orphan_articles(
                    list(orphan_ids)
                )
                log.info(
                    "sync_neo4j_with_postgres_orphans_cleaned",
                    deleted=deleted,
                    orphan_count=len(orphan_ids),
                )

            # 2. Count articles without mentions (orphan relationships)
            orphan_cleaned = await self._graph_writer.article_repo.count_articles_without_mentions()

            # 3. Detect enrichment gaps (NEO4J_DONE but NULL enrichment fields)
            incomplete = await self._article_repo.get_incomplete_articles(
                limit=self._settings.consistency_check_batch_size
            )
            reverted_count = 0
            for article in incomplete:
                log.warning(
                    "enrichment_gap_detected",
                    article_id=str(article.id),
                    url=article.source_url,
                )
                # Revert to PG_DONE so retry pipeline picks it up
                reverted = await self._article_repo.revert_to_pg_done(article.id)
                if reverted:
                    reverted_count += 1
                log.info("enrichment_gap_reverted", article_id=str(article.id))

            # 4. Entity-level consistency check
            await self._entity_consistency_check()

            log.info("sync_neo4j_with_postgres_complete", deleted=deleted, gaps=len(incomplete))
            return {
                "neo4j_orphans_deleted": deleted,
                "orphan_articles_cleaned": orphan_cleaned,
                "enrichment_gaps_detected": len(incomplete),
                "enrichment_gaps_reverted": reverted_count,
            }
        except Exception as exc:
            log.error("sync_neo4j_with_postgres_failed", error=str(exc))
            return {
                "neo4j_orphans_deleted": 0,
                "orphan_articles_cleaned": 0,
                "enrichment_gaps_detected": 0,
                "enrichment_gaps_reverted": 0,
            }

    async def _entity_consistency_check(self) -> None:
        """Check entity count consistency between Neo4j and PostgreSQL entity_vectors.

        Logs warning if mismatch detected between:
        - Neo4j entity count
        - PostgreSQL entity_vectors with valid (non-temp) neo4j_id
        """
        try:
            # Count entities in Neo4j
            neo4j_entity_ids = await self._graph_writer.entity_repo.list_all_entity_ids()
            neo4j_count = len(neo4j_entity_ids)

            # Count entities in PostgreSQL with valid neo4j_id
            pg_count = await self._vector_repo.count_entities_with_valid_neo4j_ids()

            if neo4j_count != pg_count:
                log.warning(
                    "entity_count_mismatch",
                    neo4j_count=neo4j_count,
                    pg_count=pg_count,
                    difference=abs(neo4j_count - pg_count),
                )
            else:
                log.info(
                    "entity_consistency_ok",
                    neo4j_count=neo4j_count,
                    pg_count=pg_count,
                )
        except Exception as exc:
            log.error("entity_consistency_check_failed", error=str(exc))

    @scheduled_task("retry_pipeline_processing", timeout_seconds=600)
    async def retry_pipeline_processing(self) -> int:
        """Retry failed or stuck pipeline processing.

        Scans for:
        1. Articles in PENDING state (never processed)
        2. Articles in PROCESSING state beyond timeout (stuck)
        3. Articles in FAILED state with retry_count < max_retries

        Then re-processes them through the pipeline.
        Also checks task completion status for articles with task_id.

        Returns:
            Number of articles retried.
        """
        if not self._pipeline or not self._article_repo:
            log.warning("retry_pipeline_processing_no_pipeline")
            return 0

        log.info("retry_pipeline_processing_start")
        metrics.pipeline_retry_total.labels(status="started").inc()

        retry_count = 0

        try:
            # Calculate dynamic batch size if enabled
            batch_size = self._settings.pipeline_retry_batch_size
            if self._settings.pipeline_retry_dynamic_batch:
                success_rate = await self._get_recent_success_rate()
                if success_rate >= self._settings.pipeline_retry_success_rate_threshold:
                    batch_size = min(batch_size * 2, 50)
                else:
                    batch_size = max(batch_size // 2, 5)
                batch_size = max(1, batch_size)
                log.debug(
                    "retry_pipeline_processing_batch_size",
                    batch_size=batch_size,
                    success_rate=success_rate,
                )

            # 1. Get pending articles (never processed)
            pending_articles = await self._article_repo.get_pending(limit=batch_size)

            # 2. Get stuck articles (PROCESSING beyond timeout)
            stuck_articles = await self._article_repo.get_stuck_articles(timeout_minutes=30)

            # 3. Get failed articles (eligible for retry)
            failed_articles = await self._article_repo.get_failed_articles(max_retries=3)

            articles = pending_articles + stuck_articles + failed_articles

            if not articles:
                log.info("retry_pipeline_processing_no_items")
                metrics.pipeline_retry_total.labels(status="completed").inc()
                return 0

            log.info(
                "retry_pipeline_processing_found",
                pending=len(pending_articles),
                stuck=len(stuck_articles),
                failed=len(failed_articles),
            )

            # Check task completion status for articles with task_id
            # Group articles by task_id
            task_articles: dict[uuid.UUID, list[Article]] = collections.defaultdict(list)
            for article in articles:
                if article.task_id:
                    task_articles[article.task_id].append(article)

            # For each task, check if all articles are in terminal states
            # If so, update Redis task status to "completed"
            terminal_statuses = PersistStatus.completed_statuses() | {PersistStatus.FAILED}
            for task_id, task_arts in task_articles.items():
                all_terminal = all(art.persist_status in terminal_statuses for art in task_arts)
                if all_terminal:
                    try:
                        task_key = "pipeline:task_status"
                        existing = await self._cache.client.hget(task_key, str(task_id))
                        if existing:
                            task_data = json_repair.loads(existing)
                            if task_data.get("status") not in ("completed", "failed"):
                                task_data["status"] = "completed"
                                task_data["completed_at"] = datetime.now(UTC).isoformat()
                                await self._cache.client.hset(
                                    task_key, str(task_id), json.dumps(task_data)
                                )
                                log.info(
                                    "task_auto_completed",
                                    task_id=str(task_id),
                                    article_count=len(task_arts),
                                )
                    except Exception as exc:
                        log.warning(
                            "task_completion_check_failed",
                            task_id=str(task_id),
                            error=str(exc),
                        )

            success_count = 0
            consecutive_failures = 0
            for article in articles:
                try:
                    from modules.ingestion.domain.models import RawArticle

                    raw = RawArticle(
                        url=article.source_url,
                        title=article.title,
                        body=article.body,
                        source=article.source_host or "",
                        source_host=article.source_host,
                    )

                    retry_task_id = uuid.uuid4()
                    await self._pipeline.process_batch(
                        [raw], article_ids=[article.id], task_id=retry_task_id
                    )
                    retry_count += 1
                    success_count += 1
                    consecutive_failures = 0

                    # Emit success metric based on article type
                    if article in pending_articles:
                        metrics.pipeline_retry_success_total.labels(type="pending").inc()
                    elif article in stuck_articles:
                        metrics.pipeline_retry_success_total.labels(type="stuck").inc()
                    else:
                        metrics.pipeline_retry_success_total.labels(type="failed").inc()

                    log.debug(
                        "retry_pipeline_processing_success",
                        article_id=str(article.id),
                    )

                except Exception as exc:
                    consecutive_failures += 1
                    backoff = min(2**consecutive_failures, 30)
                    log.error(
                        "retry_pipeline_processing_failed",
                        article_id=str(article.id),
                        error=str(exc),
                        backoff_seconds=backoff,
                    )
                    try:
                        await self._article_repo.mark_failed(article.id, f"Retry error: {exc!s}")
                    except Exception as mark_exc:
                        log.exception(
                            "mark_failed_error",
                            article_id=str(article.id),
                            error=str(mark_exc),
                        )
                    await asyncio.sleep(backoff)

            # Update success rate in Redis if dynamic batching is enabled
            if self._settings.pipeline_retry_dynamic_batch and articles:
                new_rate = success_count / len(articles) if articles else 1.0
                key = "pipeline:retry:success_rate"
                await self._cache.set(key, str(new_rate), ex=3600)  # 1 hour TTL
                log.debug(
                    "retry_pipeline_processing_success_rate_updated",
                    success_rate=new_rate,
                    success_count=success_count,
                    total_processed=len(articles),
                )

        except Exception as exc:
            log.error("retry_pipeline_processing_error", error=str(exc))

        metrics.pipeline_retry_total.labels(status="completed").inc()
        log.info("retry_pipeline_processing_complete", count=retry_count)
        return retry_count

    @scheduled_task("sync_pending_to_neo4j", timeout_seconds=300)
    async def sync_pending_to_neo4j(self) -> int:
        """Sync pending records to Neo4j.

        Consumes pending records from pending_sync table, writes to Neo4j,
        updates temp keys in entity_vectors, and marks records as synced.

        Note: When using LadybugDB (fallback mode), temp key updates are skipped
        since LadybugDB handles entity IDs differently from Neo4j.

        Returns:
            Number of records successfully synced.
        """
        log.info("sync_pending_to_neo4j_start")

        # Detect if using LadybugWriter (fallback mode)
        using_ladybug = type(self._graph_writer).__name__ == "LadybugWriter"
        if using_ladybug:
            log.info("sync_pending_using_ladybug_fallback")

        try:
            pending_records = await self._pending_sync_repo.get_pending(
                limit=self._settings.sync_pending_batch_size
            )

            if not pending_records:
                log.info("sync_pending_to_neo4j_no_items")
                return 0

            synced_count = 0
            for record in pending_records:
                try:
                    # Reconstruct state from payload
                    state = self._pending_sync_repo.reconstruct_state_from_payload(record.payload)
                    state["article_id"] = str(record.article_id)

                    # Write to graph database (Neo4j or LadybugDB)
                    entity_ids = await self._graph_writer.write(state)

                    # Update temp keys in entity_vectors with real entity IDs
                    # Skip for LadybugDB as it handles entity IDs differently
                    if entity_ids and record.payload.get("entity_temp_keys") and not using_ladybug:
                        temp_key_to_entity: dict[str, str] = {}
                        entity_temp_keys = record.payload.get("entity_temp_keys", {})
                        for temp_key, entity_name in entity_temp_keys.items():
                            # Find matching entity_id by entity name
                            for idx, entity in enumerate(state.get("entities", [])):
                                if entity.get("name") == entity_name and idx < len(entity_ids):
                                    temp_key_to_entity[temp_key] = entity_ids[idx]
                                    break
                        if temp_key_to_entity:
                            try:
                                await self._vector_repo.update_entity_vectors_by_temp_keys(
                                    temp_key_to_entity
                                )
                            except Exception as vec_exc:
                                log.warning(
                                    "sync_entity_vector_update_failed",
                                    error=str(vec_exc),
                                )

                    # Update article persist status
                    await self._article_repo.update_persist_status(
                        record.article_id, self._graph_writer.done_status
                    )

                    # Mark record as synced
                    await self._pending_sync_repo.mark_synced(record.id)
                    synced_count += 1

                    log.debug(
                        "sync_pending_to_neo4j_success",
                        record_id=record.id,
                        article_id=str(record.article_id),
                    )

                except Exception as exc:
                    log.error(
                        "sync_pending_to_neo4j_failed",
                        record_id=record.id,
                        article_id=str(record.article_id),
                        error=str(exc),
                    )
                    await self._pending_sync_repo.mark_failed(record.id, str(exc))

            log.info("sync_pending_to_neo4j_complete", synced=synced_count)
            return synced_count
        except Exception as exc:
            log.error("sync_pending_to_neo4j_error", error=str(exc), exc_info=True)
            # Note: Exception is caught by @scheduled_task decorator and logged.
            # Returning 0 to indicate no records were synced due to error.
            return 0

    @scheduled_task("consistency_check", timeout_seconds=600)
    async def consistency_check(self) -> dict[str, Any]:
        """Perform consistency check between Neo4j and PostgreSQL.

        Checks:
        1. Entity count comparison between Neo4j and PG entity_vectors
        2. Orphan temp keys detection in entity_vectors
        3. Stale pending records detection (>1 hour old)

        Returns:
            Dict with consistency check results.
        """
        log.info("consistency_check_start")

        results: dict[str, Any] = {
            "entity_mismatch": False,
            "orphan_temp_keys": [],
            "stale_pending": [],
        }

        try:
            # 1. Entity count comparison
            neo4j_entity_ids = await self._graph_writer.entity_repo.list_all_entity_ids()
            neo4j_count = len(neo4j_entity_ids)
            pg_count = await self._vector_repo.count_entities_with_valid_neo4j_ids()

            if neo4j_count != pg_count:
                results["entity_mismatch"] = True
                results["neo4j_count"] = neo4j_count
                results["pg_count"] = pg_count
                log.warning(
                    "consistency_entity_count_mismatch",
                    neo4j_count=neo4j_count,
                    pg_count=pg_count,
                )

            # 2. Orphan temp keys detection
            orphan_temp_keys = await self._vector_repo.get_entity_vectors_with_temp_keys()
            if orphan_temp_keys:
                results["orphan_temp_keys"] = [key for key, _ in orphan_temp_keys]
                log.warning(
                    "consistency_orphan_temp_keys",
                    count=len(orphan_temp_keys),
                )

            # 3. Stale pending records detection (>1 hour old)
            stale_pending = await self._pending_sync_repo.get_stale_pending(hours=1)
            if stale_pending:
                results["stale_pending"] = [
                    {
                        "id": r.id,
                        "article_id": str(r.article_id),
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in stale_pending
                ]
                log.warning(
                    "consistency_stale_pending",
                    count=len(stale_pending),
                )

            log.info("consistency_check_complete", results=results)
            return results
        except Exception as exc:
            log.error("consistency_check_failed", error=str(exc))
            results["error"] = str(exc)
            return results

    async def _get_recent_success_rate(self) -> float:
        """Get recent pipeline success rate from Redis.

        Reads success rate from "pipeline:retry:success_rate" key.
        Returns 1.0 if no data exists (assume success for new system).

        Returns:
            Success rate between 0.0 and 1.0.
        """
        try:
            key = "pipeline:retry:success_rate"
            rate_str = await self._cache.get(key)
            if rate_str is None:
                return 1.0
            return float(rate_str)
        except (ValueError, TypeError):
            return 1.0

    async def _reconstruct_state(self, article: Article) -> dict:
        """Reconstruct pipeline state from article for retry."""
        return {
            "article_id": str(article.id),
            "raw": type(
                "obj",
                (object,),
                {
                    "id": article.id,
                    "url": article.source_url,
                    "title": article.title,
                    "body": article.body,
                    "publish_time": article.publish_time,
                    "source": article.source_host,
                    "source_host": article.source_host,
                    "description": "",
                    "tier": 2,
                },
            )(),
            "cleaned": {
                "title": article.title,
                "body": article.body,
            },
            "category": article.category,
            "score": article.score,
        }
