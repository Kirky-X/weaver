# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Scheduled jobs for weaver backend."""

from __future__ import annotations

import collections
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import json_repair
from sqlalchemy import and_, select

from core.cache.redis import RedisClient
from core.db.models import Article, PersistStatus
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger
from core.observability.metrics import metrics
from modules.ingestion.deduplication.retry import RetryQueue
from modules.knowledge.graph.writer import Neo4jWriter
from modules.storage.postgres.article_repo import ArticleRepo
from modules.storage.postgres.pending_sync_repo import PendingSyncRepo
from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo
from modules.storage.postgres.vector_repo import VectorRepo

log = get_logger("scheduler_jobs")


class SchedulerJobs:
    """APScheduler jobs for compensation tasks.

    Implements the retry and maintenance jobs described in dev.md:
    - retry_neo4j_writes: Retry failed Neo4j writes
    - flush_retry_queue: Retry failed crawl tasks
    - update_source_auto_scores: Auto-update source authority scores
    - archive_old_neo4j_nodes: Clean up old article nodes
    - retry_pipeline_processing: Retry failed/stuck pipeline processing
    """

    def __init__(
        self,
        postgres_pool: PostgresPool,
        redis_client: RedisClient,
        neo4j_writer: Neo4jWriter,
        vector_repo: VectorRepo,
        article_repo: ArticleRepo,
        source_authority_repo: SourceAuthorityRepo,
        pending_sync_repo: PendingSyncRepo,
        pipeline: Any = None,
    ) -> None:
        self._postgres = postgres_pool
        self._redis = redis_client
        self._neo4j_writer = neo4j_writer
        self._vector_repo = vector_repo
        self._article_repo = article_repo
        self._source_authority_repo = source_authority_repo
        self._pending_sync_repo = pending_sync_repo
        self._retry_queue = RetryQueue(redis_client)
        self._pipeline = pipeline

    async def retry_neo4j_writes(self) -> int:
        """Retry failed Neo4j writes.

        Scans for articles with persist_status='pg_done' that have been
        in that state for more than 10 minutes, then attempts to write
        to Neo4j again. Prefers pending_sync payload over _reconstruct_state.

        Returns:
            Number of articles retried.
        """
        log.info("retry_neo4j_writes_start")

        async with self._postgres.session() as session:
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
                .limit(100)
            )  # Process in batches

            result = await session.execute(stmt)
            articles = result.scalars().all()

            if not articles:
                log.info("retry_neo4j_writes_no_items")
                return 0

            retry_count = 0
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
                    await self._neo4j_writer.write(state)

                    # Update status
                    article.persist_status = PersistStatus.NEO4J_DONE
                    await session.commit()
                    retry_count += 1

                    log.debug("retry_neo4j_write_success", article_id=str(article.id))

                except Exception as exc:
                    log.error(
                        "retry_neo4j_write_failed",
                        article_id=str(article.id),
                        error=str(exc),
                    )
                    # Leave in pg_done state for next retry

            log.info("retry_neo4j_writes_complete", retry_count=retry_count)
            return retry_count

    async def flush_retry_queue(self) -> int:
        """Flush expired retry queue items back to crawl queue.

        Processes crawl:retry:{host} sorted sets and re-queues
        items whose retry time has passed.

        Returns:
            Number of items requeued.
        """
        log.info("flush_retry_queue_start")

        # Get all host keys
        keys = await self._redis.keys("crawl:retry:*")
        if not keys:
            log.info("flush_retry_queue_no_keys")
            return 0

        requeue_count = 0
        now = datetime.now(UTC).timestamp()

        for key in keys:
            # Get items ready for retry
            # ZRANGEBYSCORE key -inf now
            items = await self._redis.zrangebyscore(key, "-inf", now)

            if items:
                # Remove from retry queue
                await self._redis.zrem(key, *items)

                # Add to crawl queue
                for item in items:
                    await self._redis.lpush("crawl:queue", item)
                    requeue_count += 1

        log.info("flush_retry_queue_complete", count=requeue_count)
        return requeue_count

    async def update_source_auto_scores(self) -> int:
        """Automatically update source authority scores based on history.

        Analyzes historical articles to calculate average content_check_score
        per source and updates source_authorities.auto_score.

        Returns:
            Number of sources updated.
        """
        log.info("update_source_auto_scores_start")

        async with self._postgres.session() as session:
            # Get all sources with articles
            stmt = select(Article.source_host).distinct()
            result = await session.execute(stmt)
            hosts = [row[0] for row in result if row[0]]

            update_count = 0
            for host in hosts:
                try:
                    # Calculate average credibility score for this source
                    avg_stmt = select(Article).where(
                        Article.source_host == host,
                        Article.credibility_score.isnot(None),
                    )
                    articles_result = await session.execute(avg_stmt)
                    articles = articles_result.scalars().all()

                    if articles:
                        avg_score = sum(float(a.credibility_score or 0) for a in articles) / len(
                            articles
                        )

                        # Update source authority
                        await self._source_authority_repo.update_auto_score(host, float(avg_score))
                        update_count += 1

                        log.debug(
                            "source_auto_score_updated",
                            host=host,
                            score=avg_score,
                        )

                except Exception as exc:
                    log.error(
                        "source_auto_score_failed",
                        host=host,
                        error=str(exc),
                    )

        log.info("update_source_auto_scores_complete", count=update_count)
        return update_count

    async def archive_old_neo4j_nodes(self) -> int:
        """Archive old Neo4j article nodes.

        Deletes Article nodes older than 90 days that have no
        FOLLOWED_BY relationships. Also cleans up orphan entities.

        Returns:
            Number of articles archived.
        """
        log.info("archive_old_neo4j_nodes_start")

        try:
            count = await self._neo4j_writer.archive_old_articles(days=90)
            await self._neo4j_writer.entity_repo.delete_orphan_entities()
            log.info("archive_old_neo4j_nodes_complete", count=count)
            return count
        except Exception as exc:
            log.error("archive_old_neo4j_nodes_failed", error=str(exc))
            return 0

    async def cleanup_orphan_entity_vectors(self) -> int:
        """Clean up orphan entity vectors.

        Removes entity vectors in Postgres that no longer have
        corresponding entities in Neo4j.

        Returns:
            Number of vectors cleaned up.
        """
        log.info("cleanup_orphan_entity_vectors_start")

        try:
            active_ids = await self._neo4j_writer.entity_repo.list_all_entity_ids()

            vector_repo = VectorRepo(self._postgres)

            from sqlalchemy import text

            async with self._postgres.session() as session:
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
            neo4j_ids = await self._neo4j_writer.article_repo.list_all_article_pg_ids()
            orphan_ids = set(neo4j_ids) - pg_ids

            deleted = 0
            if orphan_ids:
                deleted = await self._neo4j_writer.article_repo.delete_orphan_articles(
                    list(orphan_ids)
                )
                log.info(
                    "sync_neo4j_with_postgres_orphans_cleaned",
                    deleted=deleted,
                    orphan_count=len(orphan_ids),
                )

            # 2. Count articles without mentions (orphan relationships)
            orphan_cleaned = await self._neo4j_writer.article_repo.count_articles_without_mentions()

            # 3. Detect enrichment gaps (NEO4J_DONE but NULL enrichment fields)
            incomplete = await self._article_repo.get_incomplete_articles(limit=100)
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
            neo4j_entity_ids = await self._neo4j_writer.entity_repo.list_all_entity_ids()
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

        retry_count = 0

        try:
            # 1. Get pending articles (never processed)
            pending_articles = await self._article_repo.get_pending(limit=20)

            # 2. Get stuck articles (PROCESSING beyond timeout)
            stuck_articles = await self._article_repo.get_stuck_articles(timeout_minutes=30)

            # 3. Get failed articles (eligible for retry)
            failed_articles = await self._article_repo.get_failed_articles(max_retries=3)

            articles = pending_articles + stuck_articles + failed_articles

            if not articles:
                log.info("retry_pipeline_processing_no_items")
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
            terminal_statuses = {
                PersistStatus.NEO4J_DONE,
                PersistStatus.PG_DONE,
                PersistStatus.FAILED,
            }
            for task_id, task_arts in task_articles.items():
                all_terminal = all(art.persist_status in terminal_statuses for art in task_arts)
                if all_terminal:
                    try:
                        task_key = "pipeline:task_status"
                        existing = await self._redis.client.hget(task_key, str(task_id))
                        if existing:
                            task_data = json_repair.loads(existing)
                            if task_data.get("status") not in ("completed", "failed"):
                                task_data["status"] = "completed"
                                task_data["completed_at"] = datetime.now(UTC).isoformat()
                                await self._redis.client.hset(
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

            for article in articles:
                try:
                    from modules.ingestion.domain.models import ArticleRaw

                    raw = ArticleRaw(
                        url=article.source_url,
                        title=article.title,
                        body=article.body,
                        source=article.source_host or "",
                        source_host=article.source_host,
                    )

                    await self._pipeline.process_batch([raw], article_ids=[article.id])
                    retry_count += 1

                    log.debug(
                        "retry_pipeline_processing_success",
                        article_id=str(article.id),
                    )

                except Exception as exc:
                    log.error(
                        "retry_pipeline_processing_failed",
                        article_id=str(article.id),
                        error=str(exc),
                    )
                    try:
                        await self._article_repo.mark_failed(article.id, f"Retry error: {exc!s}")
                    except Exception:
                        pass

        except Exception as exc:
            log.error("retry_pipeline_processing_error", error=str(exc))

        log.info("retry_pipeline_processing_complete", count=retry_count)
        return retry_count

    async def update_persist_status_metrics(self) -> None:
        """Update Prometheus gauge for article persist status counts.

        Scans the articles table and updates the persist_status_count gauge
        for each status, enabling persistence failure rate alerting.
        """
        from sqlalchemy import func

        log.info("update_persist_status_metrics_start")

        try:
            async with self._postgres.session() as session:
                stmt = select(Article.persist_status, func.count(Article.id)).group_by(
                    Article.persist_status
                )
                result = await session.execute(stmt)
                rows = result.all()

                # Reset all status gauges before setting new values
                for status in PersistStatus:
                    metrics.persist_status_count.labels(status=status.value).set(0)

                for row in rows:
                    status_value = row[0].value if hasattr(row[0], "value") else str(row[0])
                    count = row[1]
                    metrics.persist_status_count.labels(status=status_value).set(count)

                log.info(
                    "persist_status_metrics_updated",
                    statuses={row[0].value: row[1] for row in rows},
                )
        except Exception as exc:
            log.error("persist_status_metrics_update_error", error=str(exc))

    async def sync_pending_to_neo4j(self) -> int:
        """Sync pending records to Neo4j.

        Consumes pending records from pending_sync table, writes to Neo4j,
        updates temp keys in entity_vectors, and marks records as synced.

        Returns:
            Number of records successfully synced.
        """
        log.info("sync_pending_to_neo4j_start")

        try:
            pending_records = await self._pending_sync_repo.get_pending(limit=100)

            if not pending_records:
                log.info("sync_pending_to_neo4j_no_items")
                return 0

            synced_count = 0
            for record in pending_records:
                try:
                    # Reconstruct state from payload
                    state = self._pending_sync_repo.reconstruct_state_from_payload(record.payload)
                    state["article_id"] = str(record.article_id)

                    # Write to Neo4j
                    neo4j_ids = await self._neo4j_writer.write(state)

                    # Update temp keys in entity_vectors with real neo4j IDs
                    if neo4j_ids and record.payload.get("entity_temp_keys"):
                        temp_key_to_neo4j: dict[str, str] = {}
                        entity_temp_keys = record.payload.get("entity_temp_keys", {})
                        for temp_key, entity_name in entity_temp_keys.items():
                            # Find matching neo4j_id by entity name
                            for idx, entity in enumerate(state.get("entities", [])):
                                if entity.get("name") == entity_name and idx < len(neo4j_ids):
                                    temp_key_to_neo4j[temp_key] = neo4j_ids[idx]
                                    break
                        if temp_key_to_neo4j:
                            await self._vector_repo.update_entity_vectors_by_temp_keys(
                                temp_key_to_neo4j
                            )

                    # Update article persist status
                    await self._article_repo.update_persist_status(
                        record.article_id, PersistStatus.NEO4J_DONE
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
            log.error("sync_pending_to_neo4j_error", error=str(exc))
            return 0

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
            neo4j_entity_ids = await self._neo4j_writer.entity_repo.list_all_entity_ids()
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

    async def _reconstruct_state(self, article: Article) -> dict:
        """Reconstruct pipeline state from article for retry."""
        # This is a simplified version - in production would need
        # to reconstruct the full state
        return {
            "article_id": str(article.id),
            "raw": type(
                "obj",
                (object,),
                {
                    "url": article.source_url,
                    "title": article.title,
                    "body": article.body,
                    "publish_time": article.publish_time,
                    "source": article.source_host,
                },
            )(),
            "cleaned": {
                "title": article.title,
                "body": article.body,
            },
            "category": article.category,
            "score": article.score,
        }


class RetryManager:
    """Manages retry queues for failed crawl operations."""

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def add_to_retry(self, host: str, item: str, retry_at: datetime) -> None:
        """Add an item to the retry queue for a host."""
        key = f"crawl:retry:{host}"
        score = retry_at.timestamp()
        await self._redis.zadd(key, {item: score})

    async def get_retry_items(self, host: str) -> list[str]:
        """Get all items ready for retry for a host."""
        key = f"crawl:retry:{host}"
        now = datetime.now(UTC).timestamp()
        return await self._redis.zrangebyscore(key, "-inf", now)

    async def remove_from_retry(self, host: str, *items: str) -> None:
        """Remove items from retry queue."""
        key = f"crawl:retry:{host}"
        if items:
            await self._redis.zrem(key, *items)
