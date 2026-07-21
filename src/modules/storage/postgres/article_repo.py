# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Article repository for PostgreSQL CRUD operations."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, bindparam, case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.change_detector import ChangeDetector
from core.db import (
    Article,
    ArticleAnalysis,
    ArticleBody,
    ArticleCore,
    ArticleProcessing,
    ArticleVersion,
    PersistStatus,
)
from core.exceptions import InvalidStateTransitionError
from core.mappers.article_state_mapper import ArticleStateMapper, _to_emotion
from core.observability import get_logger
from core.protocols import RelationalPool
from core.types.pipeline_state import PipelineState
from core.url_utils import normalize_url

if TYPE_CHECKING:
    from core.protocols.types import ArticleTitleMeta

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


# Minimum body length to consider a fetch successful (vs anti-bot error page)
_MIN_BODY_LENGTH = 200


def _build_core_body_values(
    raw: Any,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Build ArticleCore / ArticleBody kwargs + body_source for a RawArticle.

    Shared by ``insert_raw`` and ``bulk_insert_raw`` to keep body-length
    fallback, normalization, and content-hash logic in one place.

    Args:
        raw: RawArticle with non-empty url.

    Returns:
        Tuple of (core_kwargs, body_kwargs, body_source) where body_source
        is "full" or "description" (the latter when raw.body < _MIN_BODY_LENGTH
        and a description fallback is available).
    """
    effective_body = raw.body
    body_source = "full"
    if len(effective_body) < _MIN_BODY_LENGTH and raw.description:
        effective_body = raw.description
        body_source = "description"
        log.info(
            "body_too_short_using_description",
            url=raw.url,
            body_len=len(raw.body),
            desc_len=len(raw.description),
        )

    normalized_url = normalize_url(raw.url)
    content_hash = ChangeDetector.compute_hash({"title": raw.title or "", "body": effective_body})

    core_kwargs: dict[str, Any] = {
        "source_url": normalized_url,
        "source_host": raw.source_host or "",
        "source_id": raw.source_id,
        "title": raw.title or "",
        "persist_status": PersistStatus.PENDING,
        "content_hash": content_hash,
    }
    if raw.publish_time:
        core_kwargs["publish_time"] = raw.publish_time

    body_kwargs: dict[str, Any] = {"body": effective_body}
    return core_kwargs, body_kwargs, body_source


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
        # Fallback: use publish_time when LLM didn't extract event_time
        if analysis.event_time is None and state.get("cleaned", {}).get("publish_time"):
            pt = state["cleaned"]["publish_time"]
            try:
                if isinstance(pt, datetime):
                    analysis.event_time = pt
                else:
                    analysis.event_time = datetime.fromisoformat(str(pt))
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

    @staticmethod
    async def _row_affected(
        session: AsyncSession,
        result: Any,
        verify_stmt: Any | None = None,
    ) -> bool:
        """Check if UPDATE/DELETE affected any row, handling DuckDB rowcount.

        DuckDB's SQLAlchemy driver returns -1 (unknown) for all UPDATE/DELETE
        rowcount values, unlike PostgreSQL which returns the actual count.
        When rowcount is -1 and a verify_stmt is provided, verify the change
        occurred by running the verification SELECT.

        Args:
            session: AsyncSession to use for verification query.
            result: The result of execute() for UPDATE/DELETE.
            verify_stmt: Optional SQLAlchemy select() to verify post-state.
                Required for correct behavior on DuckDB.

        Returns:
            True if a row was affected (or verified on DuckDB), False otherwise.
        """
        if result.rowcount > 0:
            return True
        if result.rowcount == -1 and verify_stmt is not None:
            verify = await session.execute(verify_stmt)
            return verify.fetchone() is not None
        return False

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
        """Upsert a chunk of articles, each in its own transaction.

        Uses INSERT ... ON CONFLICT DO UPDATE for each state individually,
        eliminating the query-then-write race condition.

        Each article is upserted in a separate transaction so that a failure
        on one article does not abort the entire batch (critical for DuckDB
        which enters an aborted state on any transaction error).

        Terminal articles (state["terminal"]=True) are also persisted so the
        API can return them (e.g., "checked and found non-news"). The mapper
        sets persist_status=PG_DONE for them.

        Args:
            states: List of pipeline states to upsert.

        Returns:
            List of article UUIDs for successfully upserted articles.
        """
        if not states:
            return []

        article_ids: list[uuid.UUID] = []

        # DuckDB single-writer conflicts (TransactionContext Error: Conflict on
        # update/deletion) happen when the scheduler's retry_pipeline_processing
        # runs concurrently with other writers. Retry each article a few times
        # with exponential backoff before giving up (per project memory).
        max_retries = 3
        base_delay = 0.2

        for state in states:
            for attempt in range(max_retries):
                async with self._pool.session() as session:
                    try:
                        article_id = await self._upsert_single(session, state)
                        await session.commit()
                        article_ids.append(article_id)
                        break
                    except Exception as exc:
                        await session.rollback()
                        if attempt < max_retries - 1:
                            delay = base_delay * (2**attempt)
                            log.debug(
                                "bulk_upsert_retry",
                                attempt=attempt + 1,
                                max_retries=max_retries,
                                delay=delay,
                                error=str(exc)[:100],
                            )
                            await asyncio.sleep(delay)
                        else:
                            raw = state.get("raw")
                            url = getattr(raw, "url", "unknown") if raw else "unknown"
                            log.error("bulk_upsert_single_failed", url=url, error=str(exc))

        log.debug("bulk_upsert_chunk_complete", count=len(article_ids))
        return article_ids

    async def _upsert_single(self, session: AsyncSession, state: PipelineState) -> uuid.UUID:
        """Upsert a single article using ON CONFLICT DO UPDATE.

        Before updating an existing article, creates a version snapshot
        of the old values if content has changed.

        Args:
            session: SQLAlchemy session.
            state: Pipeline state containing article data.

        Returns:
            The article UUID.
        """
        core_values = ArticleStateMapper.to_core_values(state)
        body_values = ArticleStateMapper.to_body_values(state)
        normalized_url = core_values["source_url"]
        title = core_values["title"]
        content_hash = core_values["content_hash"]
        body = body_values["body"]

        # --- Version history: snapshot old values before upsert ---
        existing_core = await session.execute(
            select(
                ArticleCore.id,
                ArticleCore.title,
                ArticleCore.category,
                ArticleCore.score,
                ArticleCore.content_hash,
            ).where(ArticleCore.source_url == normalized_url)
        )
        existing_row = existing_core.one_or_none()

        if existing_row is not None:
            existing_id, old_title, old_category, old_score, old_hash = existing_row
            # Content changed → create version snapshot with old values
            if old_hash != content_hash:
                body_result = await session.execute(
                    select(ArticleBody.body, ArticleBody.summary).where(
                        ArticleBody.article_id == existing_id
                    )
                )
                body_row = body_result.one_or_none()
                old_body = body_row[0] if body_row else ""
                old_summary = body_row[1] if body_row else None

                changed_fields = ChangeDetector.detect_changed_fields(
                    {"title": old_title, "body": old_body, "category": old_category},
                    {"title": title, "body": body, "category": state.get("category")},
                )

                max_ver_result = await session.execute(
                    select(func.max(ArticleVersion.version)).where(
                        ArticleVersion.article_id == existing_id
                    )
                )
                next_ver = (max_ver_result.scalar_one_or_none() or 0) + 1

                session.add(
                    ArticleVersion(
                        article_id=existing_id,
                        version=next_ver,
                        title=old_title,
                        body=old_body,
                        summary=old_summary,
                        category=old_category,
                        score=old_score,
                        changed_fields=changed_fields or None,
                    )
                )
                log.debug(
                    "version_snapshot_created",
                    article_id=str(existing_id),
                    version=next_ver,
                    changed_fields=changed_fields,
                )

        # Upsert articles_core with ON CONFLICT DO UPDATE
        stmt = pg_insert(ArticleCore).values(**core_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_url"],
            set_={
                "title": case(
                    (ArticleCore.content_hash != content_hash, stmt.excluded.title),
                    else_=ArticleCore.title,
                ),
                "category": stmt.excluded.category,
                "language": stmt.excluded.language,
                "region": stmt.excluded.region,
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
        body_stmt = pg_insert(ArticleBody).values(article_id=article_id, **body_values)
        body_stmt = body_stmt.on_conflict_do_update(
            index_elements=["article_id"],
            set_={k: body_stmt.excluded[k] for k in body_values},
        )
        await session.execute(body_stmt)

        # Upsert article_analysis
        analysis_values = {"article_id": article_id, **ArticleStateMapper.to_analysis_values(state)}
        analysis_stmt = pg_insert(ArticleAnalysis).values(**analysis_values)
        analysis_stmt = analysis_stmt.on_conflict_do_update(
            index_elements=["article_id"],
            set_={k: analysis_stmt.excluded[k] for k in analysis_values if k != "article_id"},
        )
        await session.execute(analysis_stmt)

        # Update ArticleProcessing.task_id if present in state
        task_id = state.get("task_id")
        if task_id is not None:
            try:
                task_uuid = uuid.UUID(str(task_id))
                await session.execute(
                    pg_insert(ArticleProcessing)
                    .values(article_id=article_id, task_id=task_uuid)
                    .on_conflict_do_update(
                        index_elements=["article_id"],
                        set_={"task_id": task_uuid},
                    )
                )
            except (ValueError, AttributeError):
                log.warning(
                    "task_id_invalid_uuid",
                    article_id=str(article_id),
                    task_id=str(task_id),
                )

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

        normalized_urls = [normalize_url(u) for u in urls]
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
        """Mark a terminal article as PG_DONE and set fallback analysis values.

        Terminal articles (classified as not-news) get is_news=False and
        neutral fallback values so the API returns meaningful data instead
        of all-null rows.

        REM-004: Previously only filled 4 fields (persist_status, score,
        sentiment_score, is_news, sentiment), leaving 6 fields NULL
        (category, language, region, credibility_score, publish_time, summary).
        Now fills all required fields for API responses.

        Args:
            source_url: The article's source URL.

        Returns:
            True if an article was updated, False otherwise.
        """
        async with self._pool.session() as session:
            # Update ArticleCore: persist_status + score/sentiment_score fallback
            # + REM-004: category/language/region/credibility_score/publish_time fallbacks
            # Note: score and sentiment_score are in ArticleCore, NOT ArticleAnalysis
            result = await session.execute(
                update(ArticleCore)
                .where(ArticleCore.source_url == source_url)
                .where(ArticleCore.persist_status == PersistStatus.PENDING)
                .values(
                    persist_status=PersistStatus.PG_DONE,
                    score=0.0,
                    sentiment_score=0.0,
                    # REM-004: Fill fields that would otherwise be NULL for terminal articles
                    # category='其他' (CategoryType.OTHER) — valid ENUM value, see migration 26
                    category="其他",
                    language="zh",
                    region="unknown",
                    credibility_score=0.0,
                    # Use created_at as publish_time fallback (ingestion time)
                    publish_time=ArticleCore.created_at,
                    updated_at=datetime.now(UTC),
                )
            )

            # Update ArticleAnalysis: is_news=False + neutral sentiment
            # This prevents all-null rows for terminal articles
            await session.execute(
                update(ArticleAnalysis)
                .where(
                    ArticleAnalysis.article_id.in_(
                        select(ArticleCore.id).where(ArticleCore.source_url == source_url)
                    )
                )
                .values(
                    is_news=False,
                    sentiment="neutral",
                )
            )

            # REM-004: Update ArticleBody summary for terminal articles
            # Terminal articles skip cleaner, so summary would be NULL without this
            await session.execute(
                update(ArticleBody)
                .where(
                    ArticleBody.article_id.in_(
                        select(ArticleCore.id).where(ArticleCore.source_url == source_url)
                    )
                )
                .values(
                    summary="Non-news article (terminal)",
                )
            )

            await session.commit()
            updated = await self._row_affected(
                session,
                result,
                select(ArticleCore.id).where(
                    ArticleCore.source_url == source_url,
                    ArticleCore.persist_status == PersistStatus.PG_DONE,
                ),
            )
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

        normalized_url = normalize_url(raw.url)
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
                source_id=raw.source_id,
                title=raw.title or "",
                persist_status=PersistStatus.PENDING,
                content_hash=content_hash,
            )
            if raw.publish_time:
                core.publish_time = raw.publish_time

            session.add(core)
            await session.flush()

            # Insert into article_processing (vertical split from core)
            processing = ArticleProcessing(
                article_id=core.id,
                task_id=task_id,
            )
            session.add(processing)

            # Insert into article_bodies
            body = ArticleBody(
                article_id=core.id,
                body=effective_body,
            )
            session.add(body)

            # Insert into article_analysis
            analysis_values = {"article_id": core.id, "is_news": True}
            prompt_versions = {"body_source": body_source} if body_source != "full" else None
            if prompt_versions:
                analysis_values["prompt_versions"] = prompt_versions
            analysis = ArticleAnalysis(**analysis_values)
            session.add(analysis)

            await session.commit()

            log.info("article_inserted", url=raw.url, article_id=str(core.id))
            return core.id

    async def bulk_insert_raw(
        self,
        articles: list[Any],
        task_id: uuid.UUID | None = None,
    ) -> list[uuid.UUID]:
        """Bulk insert raw articles with single commit and URL dedup (P0-2 fix).

        Replaces the N-call ``insert_raw`` for-loop in
        ``DiscoveryProcessor.on_items_discovered`` (170-176) to cut N
        session round-trips + N commits down to 1+1 per crawl batch.

        Pipeline:
            1. Normalize inputs to RawArticle (reject empty URL)
            2. Batch pre-query existing URLs via ``WHERE source_url = ANY(:urls)``
            3. Single ``session.add_all`` + single ``session.commit()``
            4. Fallback to per-article ``insert_raw`` on batch failure

        Args:
            articles: List of RawArticle / NewsItem / duck-typed objects.
            task_id: Optional task ID for tracking.

        Returns:
            List of article UUIDs in input order. Existing URLs return
            their existing id; failed inserts are skipped (logged).
        """
        if not articles:
            return []

        from modules.ingestion.domain.models import NewsItem, RawArticle

        # Stage 1: normalize all inputs to RawArticle + compute normalized_url
        prepared: list[tuple[int, RawArticle, str]] = []  # (orig_idx, raw, normalized_url)
        for idx, article in enumerate(articles):
            if isinstance(article, RawArticle):
                raw = article
            elif isinstance(article, NewsItem):
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
                log.warning("bulk_insert_raw_skipped_no_url", index=idx)
                continue

            prepared.append((idx, raw, normalize_url(raw.url)))

        if not prepared:
            return []

        # Result list: fill in input order
        results: list[uuid.UUID | None] = [None] * len(articles)

        try:
            async with self._pool.session() as session:
                # Stage 2: batch pre-query existing URLs
                urls_to_check = [norm_url for _, _, norm_url in prepared]
                existing_query = select(ArticleCore.source_url, ArticleCore.id).where(
                    ArticleCore.source_url.in_(urls_to_check)
                )
                existing_result = await session.execute(existing_query)
                existing_map: dict[str, uuid.UUID] = {
                    row[0]: row[1] for row in existing_result.all()
                }

                # Stage 3: build new objects for URLs not in existing_map
                new_objects: list[Any] = []
                # Track (orig_idx, core_ref) so we can read core.id after flush
                pending_cores: list[tuple[int, ArticleCore]] = []

                for idx, raw, norm_url in prepared:
                    existing_id = existing_map.get(norm_url)
                    if existing_id is not None:
                        results[idx] = existing_id
                        log.debug("bulk_insert_raw_existing", url=raw.url, normalized=norm_url)
                        continue

                    core_kwargs, body_kwargs, body_source = _build_core_body_values(raw)
                    core = ArticleCore(**core_kwargs)
                    session.add(core)
                    pending_cores.append((idx, core))

                    new_objects.append(ArticleProcessing(article_id=core.id, task_id=task_id))
                    new_objects.append(ArticleBody(article_id=core.id, **body_kwargs))

                    analysis_values: dict[str, Any] = {"article_id": core.id, "is_news": True}
                    prompt_versions = (
                        {"body_source": body_source} if body_source != "full" else None
                    )
                    if prompt_versions:
                        analysis_values["prompt_versions"] = prompt_versions
                    new_objects.append(ArticleAnalysis(**analysis_values))

                if pending_cores:
                    # Flush to assign IDs to new ArticleCore objects
                    await session.flush()
                    for idx, core in pending_cores:
                        results[idx] = core.id

                    # add_all the dependent objects (referencing core.id)
                    session.add_all(new_objects)

                    # Single commit
                    await session.commit()

                    for idx, core in pending_cores:
                        log.info(
                            "bulk_insert_raw_inserted",
                            url=core.source_url,
                            article_id=str(core.id),
                        )

            # Fill any None (shouldn't happen, but be defensive)
            return [r for r in results if r is not None]

        except Exception as batch_exc:
            log.warning(
                "bulk_insert_raw_batch_failed_fallback",
                error=str(batch_exc),
                article_count=len(articles),
            )
            # Fallback: per-article insert_raw
            fallback_ids: list[uuid.UUID] = []
            for idx, raw, _norm_url in prepared:
                try:
                    aid = await self.insert_raw(raw, task_id=task_id)
                    fallback_ids.append(aid)
                except Exception as per_exc:
                    log.error(
                        "bulk_insert_raw_fallback_failed",
                        url=raw.url,
                        error=str(per_exc),
                    )
            return fallback_ids

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

    async def fetch_titles_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, ArticleTitleMeta]:
        """Batch fetch article metadata by PostgreSQL IDs.

        Used by graph-query callers that, after the Article node slim-down
        (design.md §D2), can only read ``pg_id`` from the graph DB and must
        look up ``title`` / ``category`` / ``publish_time`` / ``score`` from
        the relational DB in a single batched query (avoids N+1).

        Implements:
            - ArticleRepository.fetch_titles_by_pg_ids

        .. warning::
            Do NOT call this method inside a per-article loop — that
            defeats the N+1 avoidance. Pass the full ``pg_ids`` list in
            one shot.

        Args:
            pg_ids: List of article UUID strings. Empty list short-circuits
                without opening a session. Invalid UUID strings are skipped
                with a warning log (not raised). Mapping keys are lowercase
                UUID strings — callers querying the result must use
                ``pg_id.lower()`` to look up entries.

        Returns:
            Mapping of ``pg_id`` (lowercase UUID string) -> ``ArticleTitleMeta``.
            Missing IDs are omitted from the result. ``publish_time`` /
            ``score`` may be ``None`` for terminal or legacy articles.
        """
        if not pg_ids:
            return {}

        # Filter out invalid UUIDs (graph DB may carry historical dirty
        # data; one bad pg_id must not abort the entire batch — rule 12
        # "failures must be explicit"). Aggregate to a single warning log
        # with a 5-item sample to avoid log spam when many pg_ids are dirty.
        uuid_ids: list[uuid.UUID] = []
        skipped: list[str] = []
        for pid in pg_ids:
            try:
                uuid_ids.append(uuid.UUID(pid))
            except (ValueError, AttributeError, TypeError):
                skipped.append(pid)
        if skipped:
            log.warning(
                "fetch_titles_by_pg_ids_invalid_skipped",
                skipped_count=len(skipped),
                total_count=len(pg_ids),
                sample=skipped[:5],
            )
        if not uuid_ids:
            return {}

        # Chunk to avoid PG parameter limits (soft limit 65535) and DuckDB
        # plan-cache bloat. 500 keeps parse time <10ms while limiting round
        # trips to ~100 for 50K pg_ids (realistic max). Reads can use a
        # larger chunk than writes (bulk_upsert uses 50) since no
        # transaction lock is held.
        CHUNK_SIZE = 500
        mapping: dict[str, ArticleTitleMeta] = {}
        # Single shared session for all chunks — read-only queries have no
        # transaction isolation needs, unlike bulk_upsert's per-state session
        # for failure isolation. Avoids N session-construction overheads.
        async with self._pool.session() as session:
            for i in range(0, len(uuid_ids), CHUNK_SIZE):
                chunk = uuid_ids[i : i + CHUNK_SIZE]
                # expanding bindparam lets PG reuse a single plan across
                # chunks of identical size (avoids plan-cache bloat).
                stmt = select(
                    ArticleCore.id,
                    ArticleCore.title,
                    ArticleCore.category,
                    ArticleCore.publish_time,
                    ArticleCore.score,
                ).where(ArticleCore.id.in_(bindparam("ids", chunk, expanding=True)))
                result = await session.execute(stmt)
                # NOTE: row[i] indices match SELECT column order above —
                # keep in sync if reordering columns.
                for row in list(result):
                    pid_str = str(row[0])
                    mapping[pid_str] = {
                        "title": row[1],
                        "category": row[2],
                        "publish_time": row[3],
                        "score": row[4],
                    }
        log.debug(
            "fetch_titles_by_pg_ids_complete",
            requested=len(pg_ids),
            returned=len(mapping),
            skipped=len(skipped),
        )
        return mapping

    async def fetch_bodies_by_pg_ids(
        self,
        pg_ids: list[str],
    ) -> dict[str, str]:
        """Batch fetch article body content by PostgreSQL IDs.

        Mirrors ``fetch_titles_by_pg_ids`` but selects ``body`` from
        ``article_bodies`` instead of metadata columns. Used by
        ``ContextBuilder.fetch_article_bodies`` to replace the per-id
        ``repo.get`` N+1 loop with a single batched SELECT.

        Implements:
            - ArticleRepository.fetch_bodies_by_pg_ids

        .. warning::
            Do NOT call this method inside a per-article loop — that
            defeats the N+1 avoidance. Pass the full ``pg_ids`` list in
            one shot.

        Args:
            pg_ids: List of article UUID strings. Empty list short-circuits
                without opening a session. Invalid UUID strings are skipped
                with a warning log (not raised). Mapping keys are lowercase
                UUID strings — callers querying the result must use
                ``pg_id.lower()`` to look up entries.

        Returns:
            Mapping of ``pg_id`` (lowercase UUID string) -> body text.
            Missing IDs are omitted from the result (not empty string).
        """
        if not pg_ids:
            return {}

        # Filter out invalid UUIDs (graph DB may carry historical dirty data;
        # one bad pg_id must not abort the entire batch — rule 12). Aggregate
        # to a single warning log with a 5-item sample to avoid log spam.
        uuid_ids: list[uuid.UUID] = []
        skipped: list[str] = []
        for pid in pg_ids:
            try:
                uuid_ids.append(uuid.UUID(pid))
            except (ValueError, AttributeError, TypeError):
                skipped.append(pid)
        if skipped:
            log.warning(
                "fetch_bodies_by_pg_ids_invalid_skipped",
                skipped_count=len(skipped),
                total_count=len(pg_ids),
                sample=skipped[:5],
            )
        if not uuid_ids:
            return {}

        # Chunk to avoid PG parameter limits (soft limit 65535) and DuckDB
        # plan-cache bloat. 500 keeps parse time <10ms while limiting round
        # trips. Reads can use a larger chunk than writes (no transaction
        # lock held).
        CHUNK_SIZE = 500
        mapping: dict[str, str] = {}
        # Single shared session for all chunks — read-only queries have no
        # transaction isolation needs. Avoids N session-construction overheads.
        async with self._pool.session() as session:
            for i in range(0, len(uuid_ids), CHUNK_SIZE):
                chunk = uuid_ids[i : i + CHUNK_SIZE]
                stmt = select(ArticleBody.article_id, ArticleBody.body).where(
                    ArticleBody.article_id.in_(bindparam("ids", chunk, expanding=True))
                )
                result = await session.execute(stmt)
                # row[0] is article_id (UUID); row[1] is body (Text).
                for row in list(result):
                    mapping[str(row[0])] = row[1]
        log.debug(
            "fetch_bodies_by_pg_ids_complete",
            requested=len(pg_ids),
            returned=len(mapping),
            skipped=len(skipped),
        )
        return mapping

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
            return await self._row_affected(
                session,
                result,
                select(ArticleCore.id).where(
                    ArticleCore.id == article_id,
                    ArticleCore.persist_status == PersistStatus.PG_DONE,
                ),
            )

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
                        Article.persist_status.in_(PersistStatus.completed_statuses()),
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

        Uses INSERT ... ON CONFLICT to handle the case where an
        ArticleProcessing row does not yet exist.

        Args:
            article_id: The article UUID.
            stage: The current processing stage name.
        """
        async with self._pool.session() as session:
            stmt = pg_insert(ArticleProcessing).values(
                article_id=article_id,
                processing_stage=stage,
                updated_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["article_id"],
                set_={
                    "processing_stage": stmt.excluded.processing_stage,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def bulk_update_processing_stage(self, article_ids: list[uuid.UUID], stage: str) -> None:
        """Bulk update processing stage for multiple articles.

        Uses INSERT ... ON CONFLICT for each article to handle cases
        where an ArticleProcessing row does not yet exist.

        Includes DuckDB retry for single-writer transaction conflicts.

        Args:
            article_ids: List of article UUIDs to update.
            stage: The processing stage name to set.
        """
        if not article_ids:
            return

        max_retries = 3
        base_delay = 0.2
        for attempt in range(max_retries):
            try:
                async with self._pool.session() as session:
                    now = datetime.now(UTC)
                    for article_id in article_ids:
                        stmt = pg_insert(ArticleProcessing).values(
                            article_id=article_id,
                            processing_stage=stage,
                            updated_at=now,
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["article_id"],
                            set_={
                                "processing_stage": stmt.excluded.processing_stage,
                                "updated_at": stmt.excluded.updated_at,
                            },
                        )
                        await session.execute(stmt)
                    await session.commit()
                return
            except Exception as exc:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    log.debug(
                        "duckdb_bulk_update_stage_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        stage=stage,
                        error=str(exc)[:100],
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    async def mark_failed(
        self, article_id: uuid.UUID, error: str, increment_retry: bool = True
    ) -> None:
        """Mark an article as failed with error message.

        Updates ArticleCore.persist_status and ArticleProcessing fields
        (processing_error, retry_count) in the same transaction.

        Args:
            article_id: The article UUID.
            error: Error message describing the failure.
            increment_retry: Whether to increment retry count.
        """
        async with self._pool.session() as session:
            # Update persist_status on ArticleCore
            await session.execute(
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
                .values(
                    persist_status=PersistStatus.FAILED,
                    updated_at=datetime.now(UTC),
                )
            )

            # Upsert ArticleProcessing with error and retry count
            if increment_retry:
                # Get current retry count from ArticleProcessing
                result = await session.execute(
                    select(ArticleProcessing.retry_count).where(
                        ArticleProcessing.article_id == article_id
                    )
                )
                current_retry = result.scalar_one_or_none() or 0
                new_retry = current_retry + 1
            else:
                new_retry = None

            processing_values: dict[str, Any] = {
                "article_id": article_id,
                "processing_error": error,
                "updated_at": datetime.now(UTC),
            }
            if new_retry is not None:
                processing_values["retry_count"] = new_retry

            stmt = pg_insert(ArticleProcessing).values(**processing_values)
            conflict_set: dict[str, Any] = {
                "processing_error": stmt.excluded.processing_error,
                "updated_at": stmt.excluded.updated_at,
            }
            if new_retry is not None:
                conflict_set["retry_count"] = stmt.excluded.retry_count
            stmt = stmt.on_conflict_do_update(
                index_elements=["article_id"],
                set_=conflict_set,
            )
            await session.execute(stmt)
            await session.commit()

    async def mark_processing(self, article_id: uuid.UUID, stage: str) -> None:
        """Mark an article as being processed.

        Updates ArticleCore.persist_status and ArticleProcessing fields
        (processing_stage, processing_error) in the same transaction.

        Args:
            article_id: The article UUID.
            stage: The initial processing stage.
        """
        async with self._pool.session() as session:
            # Update persist_status on ArticleCore
            await session.execute(
                update(ArticleCore)
                .where(ArticleCore.id == article_id)
                .values(
                    persist_status=PersistStatus.PROCESSING,
                    updated_at=datetime.now(UTC),
                )
            )

            # Upsert ArticleProcessing with stage and clear error
            stmt = pg_insert(ArticleProcessing).values(
                article_id=article_id,
                processing_stage=stage,
                processing_error=None,
                updated_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["article_id"],
                set_={
                    "processing_stage": stmt.excluded.processing_stage,
                    "processing_error": stmt.excluded.processing_error,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await session.execute(stmt)
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

        Queries ArticleProcessing for task_id and JOINs ArticleCore
        for persist_status distribution.

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
                    func.count(ArticleProcessing.article_id).label("total_processed"),
                    func.sum(
                        sql_case(
                            (ArticleCore.persist_status == PersistStatus.PROCESSING, 1), else_=0
                        )
                    ).label("processing_count"),
                    func.sum(
                        sql_case(
                            (
                                ArticleCore.persist_status.in_(
                                    list(PersistStatus.completed_statuses())
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
                )
                .join(ArticleCore, ArticleCore.id == ArticleProcessing.article_id)
                .where(ArticleProcessing.task_id == task_id)
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
            # Count articles before dedup (DuckDB returns -1 for DELETE rowcount)
            before_result = await session.execute(text("SELECT COUNT(*) FROM articles_core"))
            count_before = before_result.scalar() or 0

            # Use ROW_NUMBER() to identify duplicates in single query
            result = await session.execute(
                text("""
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
                                                """)
            )

            # DuckDB returns -1 for DELETE rowcount; compute via before/after count
            if result.rowcount and result.rowcount > 0:
                removed_count = result.rowcount
            else:
                after_result = await session.execute(text("SELECT COUNT(*) FROM articles_core"))
                count_after = after_result.scalar() or 0
                removed_count = max(0, count_before - count_after)

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
            return await self._row_affected(
                session,
                result,
                select(ArticleCore.id).where(
                    ArticleCore.id == article_id,
                    ArticleCore.persist_status == PersistStatus.PG_DONE,
                ),
            )

    async def search_by_text(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search articles by title or body containing the query text.

        This is a fallback search when graph-based entity search returns
        no results. Uses `func.lower().contains()` for case-insensitive
        matching (DuckDB compatible; ILIKE may not work in DuckDB).

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of article dicts with id, title, body_excerpt, source_url,
            source_host, summary, publish_time.
        """
        if not query or not query.strip():
            return []

        query_lower = query.strip().lower()

        async with self._pool.session() as session:
            # Search by title first (higher priority), then by body.
            # Use func.lower().contains() for DuckDB compatibility.
            stmt = (
                select(
                    Article.id,
                    Article.title,
                    Article.body,
                    Article.source_url,
                    Article.source_host,
                    Article.summary,
                    Article.publish_time,
                )
                .where(
                    func.lower(Article.title).contains(query_lower)
                    | func.lower(Article.body).contains(query_lower)
                )
                .order_by(Article.publish_time.desc())
                .limit(limit)
            )

            try:
                result = await session.execute(stmt)
                rows = result.all()
            except Exception as exc:
                log.warning("search_by_text_failed", error=str(exc), query=query)
                return []

            articles: list[dict[str, Any]] = []
            for row in rows:
                body_text = row.body or ""
                # Extract a relevant excerpt from the body
                excerpt = self._extract_excerpt(body_text, query_lower, max_chars=300)
                articles.append(
                    {
                        "id": str(row.id),
                        "title": row.title,
                        "body_excerpt": excerpt,
                        "source_url": row.source_url,
                        "source_host": row.source_host,
                        "summary": row.summary,
                        "publish_time": row.publish_time.isoformat() if row.publish_time else None,
                    }
                )

            if articles:
                log.info(
                    "search_by_text_found",
                    count=len(articles),
                    query=query,
                )
            return articles

    @staticmethod
    def _extract_excerpt(
        body: str,
        query_lower: str,
        max_chars: int = 300,
    ) -> str:
        """Extract a relevant excerpt from article body around the query match.

        Args:
            body: Article body text.
            query_lower: Lowercased query string.
            max_chars: Maximum excerpt length.

        Returns:
            Excerpt string with ellipsis if truncated.
        """
        if not body:
            return ""

        body_lower = body.lower()
        pos = body_lower.find(query_lower)
        if pos == -1:
            # Try word-by-word matching for multi-word queries
            words = query_lower.split()
            for word in words:
                if len(word) >= 2:
                    pos = body_lower.find(word)
                    if pos != -1:
                        break

        if pos == -1:
            # No match found, return beginning
            return body[:max_chars] + ("..." if len(body) > max_chars else "")

        # Extract context around the match
        start = max(0, pos - max_chars // 3)
        end = min(len(body), start + max_chars)
        excerpt = body[start:end]
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(body):
            excerpt = excerpt + "..."
        return excerpt
