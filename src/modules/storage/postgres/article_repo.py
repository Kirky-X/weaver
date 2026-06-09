# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Article repository for PostgreSQL CRUD operations."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.change_detector import ChangeDetector
from core.db.models import (
    Article,
    ArticleAnalysis,
    ArticleBody,
    ArticleCore,
    EmotionType,
    PersistStatus,
)
from core.exceptions import InvalidStateTransitionError
from core.observability.logging import get_logger
from core.protocols import RelationalPool
from modules.ingestion.deduplication.deduplicator import Deduplicator
from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)

# Field mapping: state key -> (article_attr, extractor function)
# This centralizes all field mappings for consistency
STATE_TO_ARTICLE_FIELDS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "category": ("category", lambda v: v),
    "language": ("language", lambda v: v.strip()[:10]),
    "region": ("region", lambda v: v.strip()[:50]),
    "score": ("score", lambda v: v),
    "quality_score": ("quality_score", lambda v: v),
    "is_merged": ("is_merged", lambda v: v),
    "prompt_versions": ("prompt_versions", lambda v: v),
}


def _to_emotion(value: str | None) -> EmotionType | None:
    """Convert string emotion value to EmotionType enum for PostgreSQL ENUM column."""
    if not value:
        return None
    for member in EmotionType:
        if member.value == value or member.name.lower() == value.lower():
            return member
    return None


def _apply_state_to_core(core: ArticleCore, state: PipelineState) -> None:
    """Apply pipeline state fields to an ArticleCore object.

    Args:
        core: The ArticleCore model instance to update.
        state: Pipeline state containing article data.
    """
    # Simple field mappings for core fields
    core_fields = {"category", "language", "region", "score", "is_merged"}
    for state_key, (attr_name, extractor) in STATE_TO_ARTICLE_FIELDS.items():
        if state_key in state and state_key in core_fields:
            setattr(core, attr_name, extractor(state[state_key]))

    # Sentiment mapping (score goes to core)
    if "sentiment" in state:
        sent = state["sentiment"]
        core.sentiment_score = sent.get("sentiment_score")

    # Credibility mapping (score goes to core)
    if "credibility" in state:
        cred = state["credibility"]
        core.credibility_score = cred.get("score")

    # Merged source IDs conversion
    if "merged_source_ids" in state:
        cleaned_ids = []
        for sid in state["merged_source_ids"]:
            try:
                cleaned_ids.append(uuid.UUID(sid) if isinstance(sid, str) else sid)
            except (ValueError, AttributeError) as exc:
                log.warning("invalid_merged_source_id", source_id=sid, error=str(exc))
        core.merged_source_ids = cleaned_ids

    # Set common fields
    raw = state.get("raw")
    if raw:
        core.publish_time = getattr(raw, "publish_time", None)

    core.updated_at = datetime.now(UTC)
    core.persist_status = PersistStatus.PG_DONE


def _apply_state_to_body(body: ArticleBody, state: PipelineState) -> None:
    """Apply pipeline state fields to an ArticleBody object.

    Args:
        body: The ArticleBody model instance to update.
        state: Pipeline state containing article data.
    """
    # Summary info mapping
    if "summary_info" in state:
        si = state["summary_info"]
        body.summary = si.get("summary")
    elif state.get("merged_source_ids"):
        # Article was merged — clear stale summary
        body.summary = None


def _apply_state_to_analysis(analysis: ArticleAnalysis, state: PipelineState) -> None:
    """Apply pipeline state fields to an ArticleAnalysis object.

    Args:
        analysis: The ArticleAnalysis model instance to update.
        state: Pipeline state containing article data.
    """
    if "is_news" in state:
        analysis.is_news = state["is_news"]

    # Summary info mapping
    if "summary_info" in state:
        si = state["summary_info"]
        analysis.subjects = si.get("subjects")
        analysis.key_data = si.get("key_data")
        analysis.impact = si.get("impact")
        analysis.has_data = si.get("has_data")
        if si.get("event_time"):
            try:
                analysis.event_time = datetime.fromisoformat(si["event_time"])
            except (ValueError, TypeError):
                pass
    elif state.get("merged_source_ids"):
        # Article was merged — clear stale analysis
        analysis.subjects = None
        analysis.key_data = None
        analysis.impact = None
        analysis.has_data = None

    # Sentiment mapping
    if "sentiment" in state:
        sent = state["sentiment"]
        sentiment_value = sent.get("sentiment")
        analysis.sentiment = (
            sentiment_value.strip()[:10] if isinstance(sentiment_value, str) else sentiment_value
        )
        analysis.primary_emotion = _to_emotion(sent.get("primary_emotion"))
        analysis.emotion_targets = sent.get("emotion_targets")

    # Credibility mapping
    if "credibility" in state:
        cred = state["credibility"]
        analysis.source_credibility = cred.get("source_credibility")
        analysis.cross_verification = cred.get("cross_verification")
        analysis.content_check_score = cred.get("content_check")
        analysis.credibility_flags = cred.get("flags")
        analysis.verified_by_sources = cred.get("verified_by_sources", 0)

    # Quality score
    if "quality_score" in state:
        analysis.quality_score = state["quality_score"]

    # Data conflicts
    if "data_conflicts" in state:
        analysis.data_conflicts = state["data_conflicts"]

    # Prompt versions
    if "prompt_versions" in state:
        analysis.prompt_versions = state["prompt_versions"]


def _apply_state_to_article(article: Article, state: PipelineState) -> None:
    """Apply pipeline state fields to an Article object (backward-compatible wrapper).

    Delegates to the split table apply functions for field mapping logic.
    The Article VIEW is read-only; this wrapper exists for backward compatibility
    with code that constructs Article objects in-memory (e.g. tests).

    Args:
        article: The Article model instance to update.
        state: Pipeline state containing article data.
    """
    # Simple field mappings
    for state_key, (attr_name, extractor) in STATE_TO_ARTICLE_FIELDS.items():
        if state_key in state:
            setattr(article, attr_name, extractor(state[state_key]))

    # Summary info mapping
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
    elif state.get("merged_source_ids"):
        article.summary = None
        article.subjects = None
        article.key_data = None
        article.impact = None
        article.has_data = None

    # Sentiment mapping
    if "sentiment" in state:
        sent = state["sentiment"]
        sentiment_value = sent.get("sentiment")
        article.sentiment = (
            sentiment_value.strip()[:10] if isinstance(sentiment_value, str) else sentiment_value
        )
        article.sentiment_score = sent.get("sentiment_score")
        article.primary_emotion = _to_emotion(sent.get("primary_emotion"))
        article.emotion_targets = sent.get("emotion_targets")

    # Credibility mapping
    if "credibility" in state:
        cred = state["credibility"]
        article.credibility_score = cred.get("score")
        article.source_credibility = cred.get("source_credibility")
        article.cross_verification = cred.get("cross_verification")
        article.content_check_score = cred.get("content_check")
        article.credibility_flags = cred.get("flags")
        article.verified_by_sources = cred.get("verified_by_sources", 0)

    # Merged source IDs conversion
    if "merged_source_ids" in state:
        cleaned_ids = []
        for sid in state["merged_source_ids"]:
            try:
                cleaned_ids.append(uuid.UUID(sid) if isinstance(sid, str) else sid)
            except (ValueError, AttributeError) as exc:
                log.warning("invalid_merged_source_id", source_id=sid, error=str(exc))
        article.merged_source_ids = cleaned_ids

    # Set common fields
    raw = state.get("raw")
    if raw:
        article.publish_time = getattr(raw, "publish_time", None)

    article.updated_at = datetime.now(UTC)
    article.persist_status = PersistStatus.PG_DONE


class ArticleRepo:
    """PostgreSQL article repository.

    Handles article CRUD, persist status management,
    and URL dedup queries.

    Implements:
        - ArticleRepository: Article persistence and retrieval operations

    Args:
        pool: Relational database connection pool (PostgreSQL or DuckDB).
    """

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    def _build_analysis_values(self, article_id: uuid.UUID, state: PipelineState) -> dict:
        """Extract analysis fields from PipelineState into a dict for ArticleAnalysis insert.

        Args:
            article_id: UUID of the article.
            state: Pipeline state containing analysis data.

        Returns:
            Dict suitable for ArticleAnalysis insert/upsert.
        """
        values: dict[str, Any] = {"article_id": article_id}
        if "is_news" in state:
            values["is_news"] = state["is_news"]
        if "summary_info" in state:
            si = state["summary_info"]
            values["subjects"] = si.get("subjects")
            values["key_data"] = si.get("key_data")
            values["impact"] = si.get("impact")
            values["has_data"] = si.get("has_data")
            if si.get("event_time"):
                try:
                    values["event_time"] = datetime.fromisoformat(si["event_time"])
                except (ValueError, TypeError):
                    pass
        if "sentiment" in state:
            sent = state["sentiment"]
            sentiment_value = sent.get("sentiment")
            values["sentiment"] = (
                sentiment_value.strip()[:10]
                if isinstance(sentiment_value, str)
                else sentiment_value
            )
            values["primary_emotion"] = _to_emotion(sent.get("primary_emotion"))
            values["emotion_targets"] = sent.get("emotion_targets")
        if "credibility" in state:
            cred = state["credibility"]
            values["source_credibility"] = cred.get("source_credibility")
            values["cross_verification"] = cred.get("cross_verification")
            values["content_check_score"] = cred.get("content_check")
            values["credibility_flags"] = cred.get("flags")
            values["verified_by_sources"] = cred.get("verified_by_sources", 0)
        if "quality_score" in state:
            values["quality_score"] = state["quality_score"]
        if "data_conflicts" in state:
            values["data_conflicts"] = state["data_conflicts"]
        if "prompt_versions" in state:
            values["prompt_versions"] = state["prompt_versions"]
        return values

    async def bulk_upsert(self, states: list[PipelineState]) -> list[uuid.UUID]:
        """Bulk upsert articles from pipeline states.

        Uses INSERT ... ON CONFLICT for efficient batch operations.
        Processes states in chunks to manage memory and transaction size.

        Args:
            states: List of pipeline states containing article data.

        Returns:
            List of article UUIDs.
        """
        if not states:
            return []

        # Process in chunks to balance memory usage and transaction overhead
        CHUNK_SIZE = 50
        all_article_ids: list[uuid.UUID] = []

        for i in range(0, len(states), CHUNK_SIZE):
            chunk = states[i : i + CHUNK_SIZE]
            chunk_ids = await self._upsert_chunk(chunk)
            all_article_ids.extend(chunk_ids)

        return all_article_ids

    async def _upsert_chunk(self, states: list[PipelineState]) -> list[uuid.UUID]:
        """Upsert a chunk of articles within a single transaction.

        Uses INSERT ... ON CONFLICT DO UPDATE for each state individually,
        eliminating the query-then-write race condition.

        Args:
            states: List of pipeline states to upsert.

        Returns:
            List of article UUIDs for successfully upserted articles.
        """
        # Filter terminal states first
        valid_states = [s for s in states if not s.get("terminal")]
        if not valid_states:
            return []

        article_ids: list[uuid.UUID] = []

        async with self._pool.session() as session:
            for state in valid_states:
                try:
                    article_id = await self._upsert_single(session, state)
                    article_ids.append(article_id)
                except Exception as exc:
                    raw = state.get("raw")
                    url = getattr(raw, "url", "unknown") if raw else "unknown"
                    log.error("bulk_upsert_single_failed", url=url, error=str(exc))

            await session.commit()
            log.debug("bulk_upsert_chunk_complete", count=len(article_ids))
            return article_ids

    async def _upsert_single(self, session: AsyncSession, state: PipelineState) -> uuid.UUID:
        """Upsert a single article using ON CONFLICT DO UPDATE.

        Args:
            session: SQLAlchemy session.
            state: Pipeline state containing article data.

        Returns:
            The article UUID.
        """
        raw = state["raw"]
        normalized_url = Deduplicator.normalize_url(raw.url)
        title = state.get("cleaned", {}).get("title", getattr(raw, "title", ""))
        body = state.get("cleaned", {}).get("body", getattr(raw, "body", ""))
        content_hash = ChangeDetector.compute_hash({"title": title, "body": body})

        # Upsert articles_core with ON CONFLICT DO UPDATE
        core_values = {
            "source_url": normalized_url,
            "source_host": (
                getattr(raw, "source_host", None)
                or (raw.get("source_host") if isinstance(raw, dict) else None)
            ),
            "title": title,
            "category": state.get("category"),
            "language": state.get("language", "").strip()[:10] if state.get("language") else None,
            "region": state.get("region", "").strip()[:50] if state.get("region") else None,
            "score": state.get("score"),
            "sentiment_score": state.get("sentiment", {}).get("sentiment_score"),
            "credibility_score": state.get("credibility", {}).get("score"),
            "persist_status": PersistStatus.PG_DONE.value,
            "publish_time": getattr(raw, "publish_time", None),
            "content_hash": content_hash,
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(ArticleCore).values(**core_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_url"],
            set_={
                "title": case(
                    (ArticleCore.content_hash != content_hash, stmt.excluded.title),
                    else_=ArticleCore.title,
                ),
                "category": case(
                    (ArticleCore.content_hash != content_hash, stmt.excluded.category),
                    else_=ArticleCore.category,
                ),
                "score": stmt.excluded.score,
                "sentiment_score": stmt.excluded.sentiment_score,
                "credibility_score": stmt.excluded.credibility_score,
                "persist_status": stmt.excluded.persist_status,
                "publish_time": case(
                    (stmt.excluded.publish_time.isnot(None), stmt.excluded.publish_time),
                    else_=ArticleCore.publish_time,
                ),
                "content_hash": stmt.excluded.content_hash,
                "version": (
                    ArticleCore.version
                    + case(
                        (ArticleCore.content_hash != content_hash, 1),
                        else_=0,
                    )
                ),
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await session.execute(stmt)

        # Get the article ID
        core_result = await session.execute(
            select(ArticleCore.id).where(ArticleCore.source_url == normalized_url)
        )
        article_id = core_result.scalar_one()

        # Upsert article_bodies
        body_stmt = pg_insert(ArticleBody).values(
            article_id=article_id,
            body=body,
            summary=state.get("summary_info", {}).get("summary"),
        )
        body_stmt = body_stmt.on_conflict_do_update(
            index_elements=["article_id"],
            set_={
                "body": body_stmt.excluded.body,
                "summary": body_stmt.excluded.summary,
            },
        )
        await session.execute(body_stmt)

        # Upsert article_analysis
        analysis_values = self._build_analysis_values(article_id, state)
        analysis_stmt = pg_insert(ArticleAnalysis).values(**analysis_values)
        analysis_stmt = analysis_stmt.on_conflict_do_update(
            index_elements=["article_id"],
            set_={k: analysis_stmt.excluded[k] for k in analysis_values if k != "article_id"},
        )
        await session.execute(analysis_stmt)

        return article_id

    async def upsert(self, state: PipelineState) -> uuid.UUID:
        """Upsert an article from pipeline state.

        Uses INSERT ... ON CONFLICT DO UPDATE for atomic upsert,
        eliminating the query-then-write race condition.

        Args:
            state: Pipeline state containing article data.

        Returns:
            The article UUID.
        """
        async with self._pool.session() as session:
            try:
                article_id = await self._upsert_single(session, state)
                await session.commit()

                log.info(
                    "article_upserted",
                    article_id=str(article_id),
                    url=state["raw"].url,
                )
                return article_id
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

    async def get_by_id(self, article_id: str | uuid.UUID) -> Article | None:
        """Get an article by ID (alias for get).

        Args:
            article_id: The article UUID or string.

        Returns:
            Article instance or None if not found.
        """
        return await self.get(article_id)

    async def get_existing_urls(self, urls: list[str]) -> set[str]:
        """Check which URLs already exist in the database.

        Queries ArticleCore (actual table) rather than the Article VIEW
        for reliable existence checks.

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
                select(ArticleCore.source_url).where(ArticleCore.source_url.in_(normalized_urls))
            )
            return {row[0] for row in result}

    async def update_persist_status(
        self, article_id: uuid.UUID, status: PersistStatus | str
    ) -> None:
        """Update the persist status of an article with state validation.

        Args:
            article_id: UUID of the article to update.
            status: Target persist status.

        Raises:
            InvalidStateTransitionError: If the state transition is invalid.
        """
        # Convert string status to enum if needed
        new_status = PersistStatus(status) if isinstance(status, str) else status

        async with self._pool.session() as session:
            # Get current status from ArticleCore
            result = await session.execute(
                select(ArticleCore.persist_status).where(ArticleCore.id == article_id)
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

            # Update status on ArticleCore
            await session.execute(
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
                .values(
                    persist_status=new_status,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def mark_terminal_by_url(self, source_url: str) -> bool:
        """Mark a terminal article as PG_DONE by source URL.

        Used for articles that failed processing but need persist_status updated
        so they don't stay stuck in PENDING state.

        Args:
            source_url: The article's source URL.

        Returns:
            True if an article was updated, False otherwise.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                update(ArticleCore)
                .where(ArticleCore.source_url == source_url)
                .where(ArticleCore.persist_status == PersistStatus.PENDING)
                .values(
                    persist_status=PersistStatus.PG_DONE,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
            updated = result.rowcount > 0
            if updated:
                log.info("terminal_article_marked_done", source_url=source_url[:100])
            return updated

    async def update_credibility(
        self,
        article_id: str | uuid.UUID,
        credibility_score: float,
        cross_verification: float,
        verified_by_sources: int,
    ) -> None:
        """Update credibility fields for a specific article."""
        if isinstance(article_id, str):
            article_id = uuid.UUID(article_id)
        async with self._pool.session() as session:
            # Update credibility_score on ArticleCore
            await session.execute(
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
                .values(
                    credibility_score=credibility_score,
                    updated_at=datetime.now(UTC),
                )
            )
            # Update analysis fields on ArticleAnalysis
            await session.execute(
                update(ArticleAnalysis)
                .where(ArticleAnalysis.article_id == article_id)
                .values(
                    cross_verification=cross_verification,
                    verified_by_sources=verified_by_sources,
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
        they are processed through the pipeline. Inserts into ArticleCore
        and ArticleBody (split tables), not the Article VIEW.

        Args:
            article: Raw article data from crawler (RawArticle or NewsItem).
            task_id: Optional task ID for tracking the source pipeline run.

        Returns:
            The article UUID.
        """
        from modules.ingestion.domain.models import NewsItem, RawArticle

        # Convert if needed
        if isinstance(article, RawArticle):
            raw = article
        elif isinstance(article, NewsItem):
            # Convert NewsItem to RawArticle format
            raw = RawArticle(
                url=article.url,
                title=article.title,
                body=article.description or "",
                source=article.source,
                publish_time=article.publish_time,
                source_host=article.source_host,
                description=article.description or "",
            )
        else:
            # Try to extract attributes from arbitrary object
            raw = RawArticle(
                url=getattr(article, "url", ""),
                title=getattr(article, "title", ""),
                body=getattr(article, "description", "") or getattr(article, "body", ""),
                source=getattr(article, "source", ""),
                publish_time=getattr(article, "publish_time", None),
                source_host=getattr(article, "source_host", ""),
                description=getattr(article, "description", ""),
            )

        if not raw.url:
            raise ValueError("Article URL is required")

        # Fall back to RSS description when body is too short (e.g. anti-bot error pages).
        # A typical article body is hundreds of characters; error pages are < 200 chars.
        MIN_BODY_LENGTH = 200
        effective_body = raw.body
        body_source = "full"
        if len(effective_body) < MIN_BODY_LENGTH and raw.description:
            effective_body = raw.description
            body_source = "description"
            log.info(
                "body_too_short_using_description",
                url=raw.url,
                body_len=len(raw.body),
                desc_len=len(raw.description),
            )

        normalized_url = Deduplicator.normalize_url(raw.url)
        content_hash = ChangeDetector.compute_hash(
            {"title": raw.title or "", "body": effective_body}
        )

        async with self._pool.session() as session:
            # Check if exists using ArticleCore
            result = await session.execute(
                select(ArticleCore.id).where(ArticleCore.source_url == normalized_url)
            )
            existing_id = result.scalar_one_or_none()

            if existing_id:
                log.debug("article_already_exists", url=raw.url, normalized=normalized_url)
                return existing_id

            # Insert into articles_core
            core = ArticleCore(
                source_url=normalized_url,
                source_host=raw.source_host or "",
                title=raw.title or "",
                is_news=True,
                persist_status=PersistStatus.PENDING,
                content_hash=content_hash,
                task_id=task_id,
                prompt_versions={"body_source": body_source} if body_source != "full" else None,
            )
            if raw.publish_time:
                core.publish_time = raw.publish_time

            session.add(core)
            await session.flush()

            # Insert into article_bodies
            body = ArticleBody(
                article_id=core.id,
                body=effective_body,
            )
            session.add(body)

            await session.commit()

            log.info("article_inserted", url=raw.url, article_id=str(core.id))
            return core.id

    async def get_by_ids(self, ids: list[str]) -> list[RawArticle]:
        """Fetch RawArticle objects by IDs for queue consumer.

        Args:
            ids: List of article UUID strings.

        Returns:
            List of RawArticle objects.
        """
        if not ids:
            return []

        from modules.ingestion.domain.models import RawArticle

        async with self._pool.session() as session:
            uuid_ids = [uuid.UUID(id) for id in ids]
            query = select(Article).where(Article.id.in_(uuid_ids))
            result = await session.execute(query)
            articles = result.scalars().all()

            raw_articles = []
            for a in articles:
                raw = RawArticle(
                    url=a.source_url,
                    title=a.title or "",
                    body=a.body or "",
                    source=a.source_host or "",
                    source_host=a.source_host or "",
                    publish_time=a.publish_time,
                )
                raw_articles.append(raw)

            return raw_articles

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
            result = await session.execute(select(ArticleCore.id))
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
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
                .values(
                    persist_status=PersistStatus.PG_DONE,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def get_incomplete_articles(self, limit: int = 50) -> list[Article]:
        """Get articles with neo4j_done status but missing enrichment data.

        An article is considered incomplete if ANY of the enrichment fields
        (category, score, credibility_score, summary, quality_score) is NULL.
        This ensures articles with partial enrichment are detected and retried.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            List of incomplete articles.
        """
        from sqlalchemy import or_

        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(
                    and_(
                        Article.persist_status == PersistStatus.NEO4J_DONE,
                        or_(
                            Article.category.is_(None),
                            Article.score.is_(None),
                            Article.credibility_score.is_(None),
                            Article.summary.is_(None),
                            Article.quality_score.is_(None),
                        ),
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

        Updates are distributed across split tables:
        - category, score, credibility_score → ArticleCore
        - summary → ArticleBody
        - quality_score → ArticleAnalysis

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
        updated = False

        async with self._pool.session() as session:
            # Update ArticleCore fields
            core_updates: dict[str, Any] = {}
            if category is not None or score is not None or credibility_score is not None:
                result = await session.execute(
                    select(
                        ArticleCore.category,
                        ArticleCore.score,
                        ArticleCore.credibility_score,
                    ).where(ArticleCore.id == article_id)
                )
                core_row = result.one_or_none()
                if core_row is not None:
                    if category is not None and core_row[0] is None:
                        core_updates["category"] = category
                    if score is not None and core_row[1] is None:
                        core_updates["score"] = score
                    if credibility_score is not None and core_row[2] is None:
                        core_updates["credibility_score"] = credibility_score

            if core_updates:
                core_updates["updated_at"] = datetime.now(UTC)
                await session.execute(
                    update(ArticleCore).where(ArticleCore.id == article_id).values(**core_updates)
                )
                updated = True

            # Update ArticleBody fields
            if summary is not None:
                result = await session.execute(
                    select(ArticleBody.summary).where(ArticleBody.article_id == article_id)
                )
                current_summary = result.scalar_one_or_none()
                if current_summary is None:
                    await session.execute(
                        update(ArticleBody)
                        .where(ArticleBody.article_id == article_id)
                        .values(summary=summary)
                    )
                    updated = True

            # Update ArticleAnalysis fields
            if quality_score is not None:
                result = await session.execute(
                    select(ArticleAnalysis.quality_score).where(
                        ArticleAnalysis.article_id == article_id
                    )
                )
                current_quality = result.scalar_one_or_none()
                if current_quality is None:
                    await session.execute(
                        update(ArticleAnalysis)
                        .where(ArticleAnalysis.article_id == article_id)
                        .values(quality_score=quality_score)
                    )
                    updated = True

            if updated:
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
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
                .values(
                    processing_stage=stage,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def bulk_update_processing_stage(self, article_ids: list[uuid.UUID], stage: str) -> None:
        """Bulk update processing stage for multiple articles.

        Uses a single UPDATE ... WHERE id IN (...) query instead of
        N individual UPDATEs, reducing DB round-trips from ~1900 to ~8
        per batch.

        Args:
            article_ids: List of article UUIDs to update.
            stage: The processing stage name to set.
        """
        if not article_ids:
            return
        async with self._pool.session() as session:
            await session.execute(
                update(ArticleCore)
                .where(ArticleCore.id.in_(article_ids))
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
            # Get current retry count from ArticleCore
            result = await session.execute(
                select(ArticleCore.retry_count).where(ArticleCore.id == article_id)
            )
            current_retry = result.scalar_one_or_none() or 0

            # Build update values
            update_values: dict[str, Any] = {
                "persist_status": PersistStatus.FAILED,
                "processing_error": error,
                "updated_at": datetime.now(UTC),
            }
            if increment_retry:
                update_values["retry_count"] = current_retry + 1

            await session.execute(
                update(ArticleCore).where(ArticleCore.id == article_id).values(**update_values)
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
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
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

        Uses PostgreSQL recursive CTE to trace the merged_into chain efficiently.

        Args:
            article_id: The source article that would be merged.
            target_id: The target article to merge into.

        Returns:
            List of IDs forming the cycle if detected, None otherwise.
        """
        if article_id == target_id:
            return [article_id, target_id]

        from sqlalchemy import text

        async with self._pool.session() as session:
            # Use recursive CTE to get entire merge chain in single query
            result = await session.execute(
                text("""
                     WITH RECURSIVE merge_chain AS (SELECT id, merged_into, ARRAY[id] as path, false as cycle
                                                    FROM articles_core
                                                    WHERE id = :target_id

                                                    UNION ALL

                                                    SELECT a.id, a.merged_into, mc.path || a.id, a.id = ANY (mc.path)
                                                    FROM articles_core a
                                                             INNER JOIN merge_chain mc ON a.id = mc.merged_into
                                                    WHERE NOT mc.cycle)
                     SELECT id, path, cycle
                     FROM merge_chain
                     """),
                {"target_id": str(target_id)},
            )

            rows = result.all()
            for row in rows:
                if row.cycle:
                    cycle_path = row.path
                    log.warning(
                        "merge_cycle_detected",
                        source_id=str(article_id),
                        target_id=str(target_id),
                        cycle=cycle_path,
                    )
                    return cycle_path

            # Check if article_id appears in the chain
            for row in rows:
                if article_id in row.path:
                    cycle_path = row.path + [article_id]
                    log.warning(
                        "merge_cycle_detected",
                        source_id=str(article_id),
                        target_id=str(target_id),
                        cycle=cycle_path,
                    )
                    return cycle_path

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
                    select(ArticleCore.merged_into).where(ArticleCore.id == current_id)
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
        from sqlalchemy import case as sql_case, func

        async with self._pool.session() as session:
            result = await session.execute(
                select(
                    func.count(ArticleCore.id).label("total_processed"),
                    func.sum(
                        sql_case(
                            (ArticleCore.persist_status == PersistStatus.PROCESSING, 1), else_=0
                        )
                    ).label("processing_count"),
                    func.sum(
                        sql_case(
                            (
                                ArticleCore.persist_status.in_(
                                    [PersistStatus.NEO4J_DONE, PersistStatus.PG_DONE]
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("completed_count"),
                    func.sum(
                        sql_case((ArticleCore.persist_status == PersistStatus.FAILED, 1), else_=0)
                    ).label("failed_count"),
                    func.sum(
                        sql_case((ArticleCore.persist_status == PersistStatus.PENDING, 1), else_=0)
                    ).label("pending_count"),
                ).where(ArticleCore.task_id == task_id)
            )
            row = result.one()
            return {
                "total_processed": row.total_processed or 0,
                "processing_count": int(row.processing_count or 0),
                "completed_count": int(row.completed_count or 0),
                "failed_count": int(row.failed_count or 0),
                "pending_count": int(row.pending_count or 0),
            }

    async def deduplicate_articles(self) -> dict[str, int]:
        """Remove duplicate articles, keeping the most recent one per source_url.

        This is a cleanup method for existing data that has duplicates
        due to DuckDB not enforcing unique constraints.

        Uses a single SQL statement with ROW_NUMBER() window function
        for efficient batch deletion.

        Returns:
            Dict with 'removed' count and 'kept' count.
        """
        from sqlalchemy import text

        async with self._pool.session() as session:
            # Use ROW_NUMBER() to identify duplicates in single query
            result = await session.execute(text("""
                                                WITH ranked_articles AS (SELECT id,
                                                                                source_url,
                                                                                ROW_NUMBER() OVER (PARTITION BY source_url ORDER BY updated_at DESC) as rn
                                                                         FROM articles_core),
                                                     duplicates AS (SELECT id
                                                                    FROM ranked_articles
                                                                    WHERE rn > 1)
                                                DELETE
                                                FROM articles_core
                                                WHERE id IN (SELECT id FROM duplicates)
                                                """))

            removed_count = result.rowcount or 0

            # Count how many unique URLs we kept
            kept_result = await session.execute(
                text("SELECT COUNT(DISTINCT source_url) FROM articles_core")
            )
            kept_count = kept_result.scalar() or 0

            if removed_count > 0:
                await session.commit()
                log.info("deduplication_complete", removed=removed_count, kept=kept_count)

            return {"removed": removed_count, "kept": kept_count}

    async def get_by_status(self, status: PersistStatus, limit: int = 50) -> list[Article]:
        """Get articles by persist_status.

        Args:
            status: PersistStatus value to filter by.
            limit: Maximum number of articles to return.

        Returns:
            List of articles with the given status.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                select(Article)
                .where(Article.persist_status == status)
                .order_by(Article.updated_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def revert_to_stored(self, article_id: uuid.UUID) -> bool:
        """Revert article persist_status to PG_DONE for retry.

        Args:
            article_id: Article UUID.

        Returns:
            True if reverted, False otherwise.
        """
        async with self._pool.session() as session:
            result = await session.execute(
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
                .values(persist_status=PersistStatus.PG_DONE)
            )
            await session.commit()
            return result.rowcount > 0
