# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Article repository for PostgreSQL CRUD operations."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.change_detector import ChangeDetector
from core.constants import LanguageCode
from core.db import (
    ArticleAnalysis,
    ArticleBody,
    ArticleCore,
    ArticleProcessing,
    ArticleVersion,
    CategoryType,
    PersistStatus,
)
from core.exceptions import InvalidStateTransitionError
from core.mappers.article_state_mapper import ArticleStateMapper
from core.observability import get_logger
from core.protocols import RelationalPool
from core.types.pipeline_state import PipelineState

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class ArticleRepo:
    """PostgreSQL article repository.

    Handles article CRUD, persist status management,
    and URL dedup queries.

    Implements:
        - ArticleRepository: Article persistence and retrieval operations

    Args:
        pool: Relational database connection pool (PostgreSQL or DuckDB).
    """


class ArticleWriter:
    """ArticleWriter half of the ArticleRepo split."""

    def __init__(self, pool: RelationalPool) -> None:
        self._pool = pool

    async def bulk_upsert(self, states: list[PipelineState]) -> list[uuid.UUID | None]:
        """Bulk upsert articles from pipeline states.

        Uses INSERT ... ON CONFLICT for efficient batch operations.
        Processes states in chunks to manage memory and transaction size.

        Args:
            states: List of pipeline states containing article data.

        Returns:
            Article UUIDs position-aligned with ``states``; ``None`` marks a
            state that failed all retries (callers must not shift ids).
        """
        if not states:
            return []

        # Process in chunks to balance memory usage and transaction overhead
        CHUNK_SIZE = 50
        all_article_ids: list[uuid.UUID | None] = []

        for i in range(0, len(states), CHUNK_SIZE):
            chunk = states[i : i + CHUNK_SIZE]
            chunk_ids = await self._upsert_chunk(chunk)
            all_article_ids.extend(chunk_ids)

        return all_article_ids

    async def _upsert_chunk(self, states: list[PipelineState]) -> list[uuid.UUID | None]:
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
            Article UUIDs position-aligned with ``states``; ``None`` at a
            position means that state failed all retries and must be treated
            as not persisted (never collapse the list — callers rely on
            index alignment).
        """
        if not states:
            return []

        article_ids: list[uuid.UUID | None] = []

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
                            article_ids.append(None)

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

                # Concurrent upserts of the same URL can compute the same
                # next_ver. The snapshot is auxiliary audit data:
                # isolate it in a SAVEPOINT so a unique-constraint loser
                # rolls back only the snapshot instead of aborting the whole
                # ArticleCore/ArticleBody upsert transaction.
                try:
                    async with session.begin_nested():
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
                except AttributeError:
                    # duckdb_engine 的异步 session 未实现 SAVEPOINT
                    # （begin_nested 抛 AttributeError），且 DuckDB 在事务
                    # 错误后会进入 aborted 状态——重试也无法恢复。版本快照
                    # 是辅助审计数据，降级栈直接跳过，绝不能连累主 upsert
                    # （否则该篇拿不到 article_id，向量持久化一并丢失）。
                    log.warning(
                        "version_snapshot_savepoint_unsupported",
                        article_id=str(existing_id),
                        version=next_ver,
                        hint="duckdb_async_session lacks begin_nested; "
                        "snapshot skipped, main upsert continues",
                    )
                except IntegrityError:
                    log.warning(
                        "version_snapshot_race_skipped",
                        article_id=str(existing_id),
                        version=next_ver,
                        hint="concurrent upsert took this version number; "
                        "snapshot skipped, main upsert continues",
                    )
                else:
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
                "category": case(
                    # A degraded re-run may lack a category — never NULL out
                    # an existing classification (same guard as publish_time).
                    (stmt.excluded.category.isnot(None), stmt.excluded.category),
                    else_=ArticleCore.category,
                ),
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

        Previously only filled 4 fields (persist_status, score,
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
            # + category/language/region/credibility_score/publish_time fallbacks
            # Note: score and sentiment_score are in ArticleCore, NOT ArticleAnalysis
            result = await session.execute(
                update(ArticleCore)
                .where(ArticleCore.source_url == source_url)
                .where(ArticleCore.persist_status == PersistStatus.PENDING)
                .values(
                    persist_status=PersistStatus.PG_DONE,
                    score=0.0,
                    sentiment_score=0.0,
                    # Fill fields that would otherwise be NULL for terminal articles
                    # category='其他' (CategoryType.OTHER) — valid ENUM value, see migration 26
                    category=CategoryType.OTHER,
                    language=LanguageCode.ZH.value,
                    region="unknown",
                    credibility_score=0.0,
                    # Use created_at as publish_time fallback (ingestion time)
                    publish_time=ArticleCore.created_at,
                    updated_at=datetime.now(UTC),
                )
            )

            # Flush so the match check below observes the core UPDATE in
            # this session on both backends (DuckDB reports rowcount -1).
            await session.flush()
            matched = await self._row_affected(
                session,
                result,
                select(ArticleCore.id).where(
                    ArticleCore.source_url == source_url,
                    ArticleCore.persist_status == PersistStatus.PG_DONE,
                ),
            )
            if not matched:
                # Nothing transitioned from PENDING: an already-processed
                # article keeps its real analysis data instead of being
                # overwritten with neutral fallbacks.
                await session.rollback()
                return False

            # Update ArticleAnalysis: is_news=False + neutral sentiment
            # This prevents all-null rows for terminal articles.
            # Only reachable when this call transitioned the row (see above),
            # so the PG_DONE guard below matches exactly that row.
            await session.execute(
                update(ArticleAnalysis)
                .where(
                    ArticleAnalysis.article_id.in_(
                        select(ArticleCore.id).where(
                            ArticleCore.source_url == source_url,
                            ArticleCore.persist_status == PersistStatus.PG_DONE,
                        )
                    )
                )
                .values(
                    is_news=False,
                    sentiment="neutral",
                )
            )

            # Update ArticleBody summary for terminal articles
            # Terminal articles skip cleaner, so summary would be NULL without this
            await session.execute(
                update(ArticleBody)
                .where(
                    ArticleBody.article_id.in_(
                        select(ArticleCore.id).where(
                            ArticleCore.source_url == source_url,
                            ArticleCore.persist_status == PersistStatus.PG_DONE,
                        )
                    )
                )
                .values(
                    summary="Non-news article (terminal)",
                )
            )

            await session.commit()
            log.info("terminal_article_marked_done", source_url=source_url[:100])
            return True

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

    async def requeue_processing(self) -> None:
        """Requeue articles that were processing when shutdown occurred."""
        log.info("requeue_processing_articles")

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
