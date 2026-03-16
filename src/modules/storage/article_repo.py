"""Article repository for PostgreSQL CRUD operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Article, PersistStatus
from core.db.postgres import PostgresPool
from core.observability.logging import get_logger
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
                result = await session.execute(
                    select(Article).where(Article.source_url == raw.url)
                )
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
                article.updated_at = datetime.now(timezone.utc)

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
            result = await session.execute(
                select(Article).where(Article.id == article_id)
            )
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

        async with self._pool.session() as session:
            result = await session.execute(
                select(Article.source_url).where(Article.source_url.in_(urls))
            )
            return {row[0] for row in result}

    async def update_persist_status(
        self, article_id: uuid.UUID, status: str
    ) -> None:
        """Update the persist status of an article."""
        async with self._pool.session() as session:
            await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(
                    persist_status=status,
                    updated_at=datetime.now(timezone.utc),
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
                    updated_at=datetime.now(timezone.utc),
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

    async def insert_raw(self, article: Any) -> uuid.UUID:
        """Insert a raw article directly into the database.

        This is used for initial insertion of crawled articles before
        they are processed through the pipeline.

        Args:
            article: Raw article data from crawler (ArticleRaw or NewsItem).

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
                publish_time=getattr(article, "pubDate", None) or getattr(article, "publish_time", None),
                source_host=getattr(article, "source_host", ""),
            )

        if not raw.url:
            raise ValueError("Article URL is required")

        async with self._pool.session() as session:
            # Check if exists
            result = await session.execute(
                select(Article).where(Article.source_url == raw.url)
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
        threshold = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        async with self._pool.session() as session:
            result = await session.execute(
                select(Article).where(
                    and_(
                        Article.persist_status == PersistStatus.PROCESSING,
                        Article.updated_at < threshold,
                    )
                ).limit(50)
            )
            return list(result.scalars().all())

    async def get_failed_articles(self, max_retries: int = 3) -> list[Article]:
        """Get failed articles that are eligible for retry.

        Args:
            max_retries: Maximum retry count to consider for retry.

        Returns:
            List of failed articles that can be retried.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article).where(
                    and_(
                        Article.persist_status == PersistStatus.FAILED,
                        Article.retry_count < max_retries,
                    )
                ).limit(50)
            )
            return list(result.scalars().all())

    async def update_processing_stage(
        self, article_id: uuid.UUID, stage: str
    ) -> None:
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
                    updated_at=datetime.now(timezone.utc),
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
                "updated_at": datetime.now(timezone.utc),
            }
            if increment_retry:
                update_values["retry_count"] = current_retry + 1

            await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(**update_values)
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
                    updated_at=datetime.now(timezone.utc),
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
                    cycle_path = path[path.index(current_id):] + [current_id]
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

    async def resolve_final_merge_target(
        self, article_id: uuid.UUID
    ) -> uuid.UUID | None:
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
