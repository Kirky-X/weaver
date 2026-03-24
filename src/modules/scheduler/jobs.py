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
from core.constants import RedisKeys
from core.db.models import Article, PersistStatus
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger
from core.observability.metrics import metrics
from modules.collector.retry import RetryQueue
from modules.graph_store.neo4j_writer import Neo4jWriter
from modules.storage.article_repo import ArticleRepo
from modules.storage.source_authority_repo import SourceAuthorityRepo
from modules.storage.vector_repo import VectorRepo

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
        pipeline: Any = None,
    ) -> None:
        self._postgres = postgres_pool
        self._redis = redis_client
        self._neo4j_writer = neo4j_writer
        self._vector_repo = vector_repo
        self._article_repo = article_repo
        self._source_authority_repo = source_authority_repo
        self._retry_queue = RetryQueue(redis_client)
        self._pipeline = pipeline

    async def retry_neo4j_writes(self) -> int:
        """Retry failed Neo4j writes.

        Scans for articles with persist_status='pg_done' that have been
        in that state for more than 10 minutes, then attempts to write
        to Neo4j again.

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
                    # Get full state from article
                    # In production, would reconstruct state from article
                    state = await self._reconstruct_state(article)

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
                    await self._redis.lpush(RedisKeys.CRAWL_QUEUE, item)
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
        from sqlalchemy import func

        log.info("update_source_auto_scores_start")

        async with self._postgres.session() as session:
            # Get all sources with articles - optimized batch query
            # Calculate average credibility score per source in a single query
            stmt = (
                select(
                    Article.source_host,
                    func.avg(Article.credibility_score).label("avg_score"),
                    func.count(Article.id).label("article_count"),
                )
                .where(
                    Article.source_host.isnot(None),
                    Article.credibility_score.isnot(None),
                )
                .group_by(Article.source_host)
            )
            result = await session.execute(stmt)
            source_stats = result.all()

            update_count = 0
            for row in source_stats:
                host = row[0]
                avg_score = float(row[1]) if row[1] is not None else 0.0

                try:
                    # Update source authority with batch-calculated score
                    await self._source_authority_repo.update_auto_score(host, avg_score)
                    update_count += 1

                    log.debug(
                        "source_auto_score_updated",
                        host=host,
                        avg_score=avg_score,
                        article_count=row[2],
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

    async def sync_neo4j_with_postgres(self) -> int:
        """Synchronize Neo4j articles with PostgreSQL.

        Detects and cleans up two types of inconsistency:
        1. Orphan Neo4j nodes (in Neo4j but not in PostgreSQL)
        2. Enrichment gaps (NEO4J_DONE status but NULL enrichment fields)

        Returns:
            Number of orphan articles deleted.
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

            # 2. Detect enrichment gaps (NEO4J_DONE but NULL enrichment fields)
            incomplete = await self._article_repo.get_incomplete_articles(limit=100)
            for article in incomplete:
                log.warning(
                    "enrichment_gap_detected",
                    article_id=str(article.id),
                    url=article.source_url,
                )
                # Revert to PG_DONE so retry pipeline picks it up
                await self._article_repo.revert_to_pg_done(article.id)
                log.info("enrichment_gap_reverted", article_id=str(article.id))

            log.info("sync_neo4j_with_postgres_complete", deleted=deleted, gaps=len(incomplete))
            return deleted
        except Exception as exc:
            log.error("sync_neo4j_with_postgres_failed", error=str(exc))
            return 0

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
                        task_key = RedisKeys.PIPELINE_TASK_STATUS
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
                    from modules.collector.models import ArticleRaw

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
