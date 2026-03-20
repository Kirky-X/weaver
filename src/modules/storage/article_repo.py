# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Article repository for PostgreSQL CRUD operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Article, PersistStatus
from core.db.postgres import PostgresPool
from core.exceptions import InvalidStateTransitionError
from core.observability.logging import get_logger
from modules.collector.deduplicator import Deduplicator
from modules.pipeline.state import PipelineState

log = get_logger("article_repo")


class ArticleRepo:
    """PostgreSQL article repository.

    Handles article CRUD, persist status management,
    and URL dedup queries.

    Args:
        pool: PostgreSQL connection pool.
    """

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def bulk_upsert(self, states: list[PipelineState]) -> list[uuid.UUID]:
        """Bulk upsert articles from pipeline states.

        Uses INSERT ... ON CONFLICT for efficient batch operations.

        Args:
            states: List of pipeline states containing article data.

        Returns:
            List of article UUIDs.
        """
        if not states:
            return []

        async with self._pool.session() as session:
            article_ids = []
            for state in states:
                if state.get("terminal"):
                    continue
                try:
                    aid = await self._upsert_single(session, state)
                    article_ids.append(aid)
                except Exception as exc:
                    log.error("bulk_upsert_single_failed", error=str(exc))
            await session.commit()
            return article_ids

    async def _upsert_single(self, session: AsyncSession, state: PipelineState) -> uuid.UUID:
        """Upsert a single article within an existing session."""
        raw = state["raw"]

        result = await session.execute(select(Article).where(Article.source_url == raw.url))
        article = result.scalar_one_or_none()

        if article is None:
            article = Article(
                source_url=raw.url,
                source_host=raw.source_host,
                is_news=state.get("is_news", True),
                title=state.get("cleaned", {}).get("title", raw.title),
                body=state.get("cleaned", {}).get("body", raw.body),
            )
            session.add(article)

        if "category" in state:
            article.category = state["category"]
        if "language" in state:
            article.language = state["language"]
        if "region" in state:
            article.region = state["region"]
        if "summary_info" in state:
            si = state["summary_info"]
            article.summary = si.get("summary")
            article.subjects = si.get("subjects")
            article.key_data = si.get("key_data")
            article.impact = si.get("impact")
            article.has_data = si.get("has_data")
            if si.get("event_time"):
                try:
                    article.event_time = datetime.fromisoformat(si["event_time"])
                except (ValueError, TypeError):
                    pass
        if "score" in state:
            article.score = state["score"]
        if "quality_score" in state:
            article.quality_score = state["quality_score"]
        if "sentiment" in state:
            sent = state["sentiment"]
            article.sentiment = sent.get("sentiment")
            article.sentiment_score = sent.get("sentiment_score")
            article.primary_emotion = sent.get("primary_emotion")
            article.emotion_targets = sent.get("emotion_targets")
        if "credibility" in state:
            cred = state["credibility"]
            article.credibility_score = cred.get("score")
            article.source_credibility = cred.get("source_credibility")
            article.cross_verification = cred.get("cross_verification")
            article.content_check_score = cred.get("content_check")
            article.credibility_flags = cred.get("flags")
            article.verified_by_sources = cred.get("verified_by_sources", 0)
        if "is_merged" in state:
            article.is_merged = state["is_merged"]
        if "merged_source_ids" in state:
            article.merged_source_ids = [
                uuid.UUID(sid) if isinstance(sid, str) else sid
                for sid in state["merged_source_ids"]
            ]
        if "prompt_versions" in state:
            article.prompt_versions = state["prompt_versions"]

        article.publish_time = raw.publish_time
        article.updated_at = datetime.now(UTC)

        await session.flush()
        return article.id

    async def upsert(self, state: PipelineState) -> uuid.UUID:
        """Upsert an article from pipeline state.

        Creates or updates the article record in PostgreSQL.

        Args:
            state: Pipeline state containing article data.

        Returns:
            The article UUID.
        """
        async with self._pool.session() as session:
            try:
                raw = state["raw"]

                # Check if exists
                result = await session.execute(select(Article).where(Article.source_url == raw.url))
                article = result.scalar_one_or_none()

                if article is None:
                    article = Article(
                        source_url=raw.url,
                        source_host=raw.source_host,
                        is_news=state.get("is_news", True),
                        title=state.get("cleaned", {}).get("title", raw.title),
                        body=state.get("cleaned", {}).get("body", raw.body),
                    )
                    session.add(article)

                # Update fields from pipeline state
                if "category" in state:
                    log.debug("upsert_category", category=state["category"])
                    article.category = state["category"]
                if "language" in state:
                    article.language = state["language"]
                if "region" in state:
                    article.region = state["region"]
                if "summary_info" in state:
                    si = state["summary_info"]
                    article.summary = si.get("summary")
                    article.subjects = si.get("subjects")
                    article.key_data = si.get("key_data")
                    article.impact = si.get("impact")
                    article.has_data = si.get("has_data")
                    if si.get("event_time"):
                        try:
                            article.event_time = datetime.fromisoformat(si["event_time"])
                        except (ValueError, TypeError):
                            pass
                if "score" in state:
                    article.score = state["score"]
                if "quality_score" in state:
                    article.quality_score = state["quality_score"]
                if "sentiment" in state:
                    sent = state["sentiment"]
                    log.debug("upsert_sentiment", sentiment=sent.get("sentiment"))
                    article.sentiment = sent.get("sentiment")
                    article.sentiment_score = sent.get("sentiment_score")
                    article.primary_emotion = sent.get("primary_emotion")
                    article.emotion_targets = sent.get("emotion_targets")
                if "credibility" in state:
                    cred = state["credibility"]
                    article.credibility_score = cred.get("score")
                    article.source_credibility = cred.get("source_credibility")
                    article.cross_verification = cred.get("cross_verification")
                    article.content_check_score = cred.get("content_check")
                    article.credibility_flags = cred.get("flags")
                    article.verified_by_sources = cred.get("verified_by_sources", 0)
                if "is_merged" in state:
                    article.is_merged = state["is_merged"]
                if "merged_source_ids" in state:
                    article.merged_source_ids = [
                        uuid.UUID(sid) if isinstance(sid, str) else sid
                        for sid in state["merged_source_ids"]
                    ]
                if "prompt_versions" in state:
                    article.prompt_versions = state["prompt_versions"]

                article.publish_time = raw.publish_time
                article.updated_at = datetime.now(UTC)

                await session.commit()
                await session.refresh(article)

                log.info("article_upserted", article_id=str(article.id), url=raw.url)
                return article.id
            except Exception as exc:
                log.error("article_upsert_error", error=str(exc), error_type=type(exc).__name__)
                await session.rollback()
                raise

    async def get(self, article_id: str | uuid.UUID) -> Article | None:
        """Get an article by ID."""
        if isinstance(article_id, str):
            article_id = uuid.UUID(article_id)
        async with self._pool.session() as session:
            result = await session.execute(select(Article).where(Article.id == article_id))
            return result.scalar_one_or_none()

    async def get_existing_urls(self, urls: list[str]) -> set[str]:
        """Check which URLs already exist in the database.

        Args:
            urls: List of URLs to check.

        Returns:
            Set of URLs that exist in the database.
        """
        if not urls:
            return set()

        normalized_urls = [Deduplicator.normalize_url(u) for u in urls]
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article.source_url).where(Article.source_url.in_(normalized_urls))
            )
            return {row[0] for row in result}

    async def update_persist_status(self, article_id: uuid.UUID, status: str) -> None:
        """Update the persist status of an article with state validation.

        Args:
            article_id: UUID of the article to update.
            status: Target persist status.

        Raises:
            InvalidStateTransitionError: If the state transition is invalid.
        """
        # Convert string status to enum if needed
        if isinstance(status, str):
            new_status = PersistStatus(status)
        else:
            new_status = status

        async with self._pool.session() as session:
            # Get current status
            result = await session.execute(
                select(Article.persist_status).where(Article.id == article_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                log.warning(
                    "update_persist_status_article_not_found",
                    article_id=str(article_id),
                )
                return

            current_status = row

            # Validate state transition
            if not PersistStatus.is_valid_transition(current_status, new_status):
                raise InvalidStateTransitionError(
                    from_status=current_status.value,
                    to_status=new_status.value,
                )

            # Update status
            await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(
                    persist_status=new_status,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def update_credibility(
        self,
        article_id: str,
        credibility_score: float,
        cross_verification: float,
        verified_by_sources: int,
    ) -> None:
        """Update credibility fields for a specific article."""
        if isinstance(article_id, str):
            article_id = uuid.UUID(article_id)
        async with self._pool.session() as session:
            await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(
                    credibility_score=credibility_score,
                    cross_verification=cross_verification,
                    verified_by_sources=verified_by_sources,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def get_pending_neo4j(self, limit: int = 50) -> list[Article]:
        """Get articles with persist_status='pg_done' for Neo4j retry."""
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(Article.persist_status == PersistStatus.PG_DONE)
                .order_by(Article.updated_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def requeue_processing(self) -> None:
        """Requeue articles that were processing when shutdown occurred."""
        log.info("requeue_processing_articles")

    async def get_pending(self, limit: int = 50) -> list[Article]:
        """Get articles with persist_status='PENDING' for processing.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            List of pending articles.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(Article.persist_status == PersistStatus.PENDING)
                .order_by(Article.created_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def insert_raw(self, article: Any, task_id: uuid.UUID | None = None) -> uuid.UUID:
        """Insert a raw article directly into the database.

        This is used for initial insertion of crawled articles before
        they are processed through the pipeline.

        Args:
            article: Raw article data from crawler (ArticleRaw or NewsItem).
            task_id: Optional task ID for tracking the source pipeline run.

        Returns:
            The article UUID.
        """
        from modules.collector.models import ArticleRaw as RawModel
        from modules.source.models import NewsItem

        # Convert if needed
        if isinstance(article, RawModel):
            raw = article
        elif isinstance(article, NewsItem):
            # Convert NewsItem to ArticleRaw format
            raw = RawModel(
                url=article.url,
                title=article.title,
                body=article.description or "",  # Use description as body
                source=article.source,
                publish_time=article.pubDate,
                source_host=article.source_host,
            )
        else:
            # Try to extract attributes from arbitrary object
            raw = RawModel(
                url=getattr(article, "url", ""),
                title=getattr(article, "title", ""),
                body=getattr(article, "description", "") or getattr(article, "body", ""),
                source=getattr(article, "source", ""),
                publish_time=getattr(article, "pubDate", None)
                or getattr(article, "publish_time", None),
                source_host=getattr(article, "source_host", ""),
            )

        if not raw.url:
            raise ValueError("Article URL is required")

        normalized_url = Deduplicator.normalize_url(raw.url)
        async with self._pool.session() as session:
            # Check if exists using normalized URL
            result = await session.execute(
                select(Article).where(Article.source_url == normalized_url)
            )
            existing = result.scalar_one_or_none()

            if existing:
                log.debug("article_already_exists", url=raw.url)
                return existing.id

            # Create new article with raw data
            # Use persist_status enum directly
            article = Article(
                source_url=raw.url,
                source_host=raw.source_host or "",
                title=raw.title or "",
                body=raw.body or "",
                is_news=True,
                persist_status=PersistStatus.PENDING,
            )
            article.task_id = task_id
            if raw.publish_time:
                article.publish_time = raw.publish_time

            session.add(article)
            await session.commit()

            log.info("article_inserted", url=raw.url, article_id=str(article.id))
            return article.id

    async def get_stuck_articles(self, timeout_minutes: int = 30) -> list[Article]:
        """Get articles stuck in PROCESSING state beyond timeout.

        These are articles that were being processed but the pipeline
        was interrupted before completion.

        Args:
            timeout_minutes: Minutes after which an article is considered stuck.

        Returns:
            List of stuck articles.
        """
        threshold = datetime.now(UTC) - timedelta(minutes=timeout_minutes)

        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(
                    and_(
                        Article.persist_status == PersistStatus.PROCESSING,
                        Article.updated_at < threshold,
                    )
                )
                .limit(50)
            )
            return list(result.scalars().all())

    async def get_all_article_ids(self) -> set[str]:
        """Get all article IDs from PostgreSQL.

        Returns:
            Set of article ID strings.
        """
        async with self._pool.session() as session:
            result = await session.execute(select(Article.id))
            return {str(row[0]) for row in result}

    async def revert_to_pg_done(self, article_id: uuid.UUID) -> bool:
        """Force-revert an article to PG_DONE for enrichment retry.

        This bypasses state machine validation because it's a recovery
        action for data integrity issues.

        Returns:
            True if reverted, False if article not found.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(
                    persist_status=PersistStatus.PG_DONE,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def get_incomplete_articles(self, limit: int = 50) -> list[Article]:
        """Get articles with neo4j_done status but missing enrichment data.

        These are articles that were marked complete but have NULL enrichment
        fields, indicating a terminal-path data gap.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            List of incomplete articles.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(
                    and_(
                        Article.persist_status == PersistStatus.NEO4J_DONE,
                        Article.category.is_(None),
                        Article.score.is_(None),
                        Article.credibility_score.is_(None),
                        Article.summary.is_(None),
                    )
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def update_enrichment_if_null(
        self,
        article_id: uuid.UUID,
        category: str | None = None,
        score: float | None = None,
        credibility_score: float | None = None,
        summary: str | None = None,
        quality_score: float | None = None,
    ) -> bool:
        """Update enrichment fields only where they are currently NULL (idempotent).

        This method only updates fields that are NULL, leaving existing values
        untouched. Running multiple times produces the same result (idempotent).

        Args:
            article_id: UUID of the article to update.
            category: Category to set if currently NULL.
            score: Score to set if currently NULL.
            credibility_score: Credibility score to set if currently NULL.
            summary: Summary to set if currently NULL.
            quality_score: Quality score to set if currently NULL.

        Returns:
            True if any field was updated, False otherwise.
        """
        async with self._pool.session() as session:
            result = await session.execute(select(Article).where(Article.id == article_id))
            article = result.scalar_one_or_none()
            if not article:
                return False

            updated = False
            if category is not None and article.category is None:
                article.category = category
                updated = True
            if score is not None and article.score is None:
                article.score = score
                updated = True
            if credibility_score is not None and article.credibility_score is None:
                article.credibility_score = credibility_score
                updated = True
            if summary is not None and article.summary is None:
                article.summary = summary
                updated = True
            if quality_score is not None and article.quality_score is None:
                article.quality_score = quality_score
                updated = True

            if updated:
                article.updated_at = datetime.now(UTC)
                await session.commit()
            return updated

    async def get_failed_articles(self, max_retries: int = 3) -> list[Article]:
        """Get failed articles that are eligible for retry.

        Args:
            max_retries: Maximum retry count to consider for retry.

        Returns:
            List of failed articles that can be retried.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(
                    and_(
                        Article.persist_status == PersistStatus.FAILED,
                        Article.retry_count < max_retries,
                    )
                )
                .limit(50)
            )
            return list(result.scalars().all())

    async def update_processing_stage(self, article_id: uuid.UUID, stage: str) -> None:
        """Update the current processing stage of an article.

        Args:
            article_id: The article UUID.
            stage: The current processing stage name.
        """
        async with self._pool.session() as session:
            await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(
                    processing_stage=stage,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def mark_failed(
        self, article_id: uuid.UUID, error: str, increment_retry: bool = True
    ) -> None:
        """Mark an article as failed with error message.

        Args:
            article_id: The article UUID.
            error: Error message describing the failure.
            increment_retry: Whether to increment retry count.
        """
        async with self._pool.session() as session:
            # Get current retry count
            result = await session.execute(
                select(Article.retry_count).where(Article.id == article_id)
            )
            current_retry = result.scalar_one_or_none() or 0

            # Build update values
            update_values = {
                "persist_status": PersistStatus.FAILED,
                "processing_error": error,
                "updated_at": datetime.now(UTC),
            }
            if increment_retry:
                update_values["retry_count"] = current_retry + 1

            await session.execute(
                update(Article).where(Article.id == article_id).values(**update_values)
            )
            await session.commit()

    async def mark_processing(self, article_id: uuid.UUID, stage: str) -> None:
        """Mark an article as being processed.

        Args:
            article_id: The article UUID.
            stage: The initial processing stage.
        """
        async with self._pool.session() as session:
            await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(
                    persist_status=PersistStatus.PROCESSING,
                    processing_stage=stage,
                    processing_error=None,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def detect_merge_cycle(
        self, article_id: uuid.UUID, target_id: uuid.UUID
    ) -> list[uuid.UUID] | None:
        """Detect if setting merged_to target would create a cycle.

        Uses BFS to trace the merged_into chain from target_id.
        If article_id appears in the chain, a cycle would be created.

        Args:
            article_id: The source article that would be merged.
            target_id: The target article to merge into.

        Returns:
            List of IDs forming the cycle if detected, None otherwise.
        """
        if article_id == target_id:
            return [article_id, target_id]

        visited: set[uuid.UUID] = {article_id}
        path: list[uuid.UUID] = []
        current_id: uuid.UUID | None = target_id

        async with self._pool.session() as session:
            while current_id is not None:
                if current_id in visited:
                    cycle_path = path[path.index(current_id) :] + [current_id]
                    log.warning(
                        "merge_cycle_detected",
                        source_id=str(article_id),
                        target_id=str(target_id),
                        cycle=cycle_path,
                    )
                    return cycle_path

                visited.add(current_id)
                path.append(current_id)

                result = await session.execute(
                    select(Article.merged_into).where(Article.id == current_id)
                )
                current_id = result.scalar_one_or_none()

        return None

    async def resolve_final_merge_target(self, article_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve the final target of a merge chain.

        Follows the merged_into chain to the end, detecting cycles.

        Args:
            article_id: The article to resolve.

        Returns:
            The final target ID, or None if no merge.
        """
        visited: set[uuid.UUID] = set()
        current_id: uuid.UUID | None = article_id

        async with self._pool.session() as session:
            while current_id is not None:
                if current_id in visited:
                    log.error(
                        "merge_cycle_in_chain",
                        article_id=str(article_id),
                        cycle_at=str(current_id),
                    )
                    return None

                visited.add(current_id)

                result = await session.execute(
                    select(Article.merged_into).where(Article.id == current_id)
                )
                next_id = result.scalar_one_or_none()

                if next_id is None:
                    return current_id

                current_id = next_id

        return None

    async def get_task_progress_stats(self, task_id: uuid.UUID) -> dict[str, int]:
        """Get progress statistics for a specific task.

        Args:
            task_id: The task UUID to query.

        Returns:
            Dictionary with total_processed, processing_count, completed_count,
            failed_count, pending_count.
        """
        from sqlalchemy import case, func

        async with self._pool.session() as session:
            result = await session.execute(
                select(
                    func.count(Article.id).label("total_processed"),
                    func.sum(
                        case((Article.persist_status == PersistStatus.PROCESSING, 1), else_=0)
                    ).label("processing_count"),
                    func.sum(
                        case(
                            (
                                Article.persist_status.in_(
                                    [PersistStatus.NEO4J_DONE, PersistStatus.PG_DONE]
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("completed_count"),
                    func.sum(
                        case((Article.persist_status == PersistStatus.FAILED, 1), else_=0)
                    ).label("failed_count"),
                    func.sum(
                        case((Article.persist_status == PersistStatus.PENDING, 1), else_=0)
                    ).label("pending_count"),
                ).where(Article.task_id == task_id)
            )
            row = result.one()
            return {
                "total_processed": row.total_processed or 0,
                "processing_count": int(row.processing_count or 0),
                "completed_count": int(row.completed_count or 0),
                "failed_count": int(row.failed_count or 0),
                "pending_count": int(row.pending_count or 0),
            }
