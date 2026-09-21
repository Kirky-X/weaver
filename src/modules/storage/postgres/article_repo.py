# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X
"""PostgreSQL article repository — composite facade.

Combines ArticleReader / ArticleWriter / RawBulkWriter; the public surface
is unchanged so all callers keep working.

Implements:
    - ArticleRepository: Article persistence and retrieval operations
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.protocols.types import ArticleTitleMeta
    from core.types.ingestion_models import RawArticle


from core.db import Article, PersistStatus
from core.observability import get_logger
from core.types.pipeline_state import PipelineState
from modules.storage.postgres.article_reader import ArticleReader
from modules.storage.postgres.article_writer import ArticleWriter
from modules.storage.postgres.raw_bulk_writer import RawBulkWriter

log = get_logger(__name__)


class ArticleRepo:
    """PostgreSQL article repository — composite facade.

    Implements: ArticleRepository

    All public methods delegate to the three collaborating halves which
    share the same connection pool.
    """

    def __init__(self, pool) -> None:
        self._pool = pool
        self._reader = ArticleReader(pool)
        self._writer = ArticleWriter(pool)
        self._raw_bulk = RawBulkWriter(pool)

    async def get(self, article_id: str | uuid.UUID) -> Article | None:
        return await self._reader.get(article_id)

    async def get_by_id(self, article_id: str | uuid.UUID) -> Article | None:
        return await self._reader.get_by_id(article_id)

    async def get_by_ids(self, ids: list[str]) -> list[RawArticle]:
        return await self._reader.get_by_ids(ids)

    async def get_existing_urls(self, urls: list[str]) -> set[str]:
        return await self._reader.get_existing_urls(urls)

    async def get_existing_titles(self, titles: set[str]) -> set[str]:
        return await self._reader.get_existing_titles(titles)

    async def get_pending(self, limit: int = 50) -> list[Article]:
        return await self._reader.get_pending(limit)

    async def get_pending_neo4j(self, limit: int = 50) -> list[Article]:
        return await self._reader.get_pending_neo4j(limit)

    async def get_stuck_articles(self, timeout_minutes: int = 30) -> list[Article]:
        return await self._reader.get_stuck_articles(timeout_minutes)

    async def get_all_article_ids(
        self,
    ) -> set[str]:
        return await self._reader.get_all_article_ids()

    async def get_incomplete_articles(self, limit: int = 50) -> list[Article]:
        return await self._reader.get_incomplete_articles(limit)

    async def get_failed_articles(self, max_retries: int = 3) -> list[Article]:
        return await self._reader.get_failed_articles(max_retries)

    async def fetch_titles_by_pg_ids(self, pg_ids: list[str]) -> dict[str, ArticleTitleMeta]:
        return await self._reader.fetch_titles_by_pg_ids(pg_ids)

    async def fetch_bodies_by_pg_ids(self, pg_ids: list[str]) -> dict[str, str]:
        return await self._reader.fetch_bodies_by_pg_ids(pg_ids)

    async def get_task_progress_stats(self, task_id: uuid.UUID) -> dict[str, int]:
        return await self._reader.get_task_progress_stats(task_id)

    async def search_by_text(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return await self._reader.search_by_text(query, limit)

    async def detect_merge_cycle(
        self, article_id: uuid.UUID, target_id: uuid.UUID
    ) -> list[uuid.UUID] | None:
        return await self._reader.detect_merge_cycle(article_id, target_id)

    async def resolve_final_merge_target(self, article_id: uuid.UUID) -> uuid.UUID | None:
        return await self._reader.resolve_final_merge_target(article_id)

    async def bulk_upsert(self, states: list[PipelineState]) -> list[uuid.UUID | None]:
        return await self._writer.bulk_upsert(states)

    async def upsert(self, state: PipelineState) -> uuid.UUID:
        return await self._writer.upsert(state)

    async def update_persist_status(
        self, article_id: uuid.UUID, status: PersistStatus | str
    ) -> None:
        return await self._writer.update_persist_status(article_id, status)

    async def mark_terminal_by_url(self, source_url: str) -> bool:
        return await self._writer.mark_terminal_by_url(source_url)

    async def update_credibility(
        self,
        article_id: str | uuid.UUID,
        credibility_score: float,
        cross_verification: float,
        verified_by_sources: int,
    ) -> None:
        return await self._writer.update_credibility(
            article_id, credibility_score, cross_verification, verified_by_sources
        )

    async def requeue_processing(
        self,
    ) -> None:
        return await self._writer.requeue_processing()

    async def revert_to_pg_done(self, article_id: uuid.UUID) -> bool:
        return await self._writer.revert_to_pg_done(article_id)

    async def update_enrichment_if_null(
        self,
        article_id: uuid.UUID,
        category: str | None = None,
        score: float | None = None,
        credibility_score: float | None = None,
        summary: str | None = None,
        quality_score: float | None = None,
    ) -> bool:
        return await self._writer.update_enrichment_if_null(
            article_id, category, score, credibility_score, summary, quality_score
        )

    async def update_processing_stage(self, article_id: uuid.UUID, stage: str) -> None:
        return await self._writer.update_processing_stage(article_id, stage)

    async def bulk_update_processing_stage(self, article_ids: list[uuid.UUID], stage: str) -> None:
        return await self._writer.bulk_update_processing_stage(article_ids, stage)

    async def mark_failed(
        self, article_id: uuid.UUID, error: str, increment_retry: bool = True
    ) -> None:
        return await self._writer.mark_failed(article_id, error, increment_retry)

    async def mark_processing(self, article_id: uuid.UUID, stage: str) -> None:
        return await self._writer.mark_processing(article_id, stage)

    async def revert_to_stored(self, article_id: uuid.UUID) -> bool:
        return await self._writer.revert_to_stored(article_id)

    async def deduplicate_articles(
        self,
    ) -> dict[str, int]:
        return await self._writer.deduplicate_articles()

    async def insert_raw(self, article: Any, task_id: uuid.UUID | None = None) -> uuid.UUID:
        return await self._raw_bulk.insert_raw(article, task_id)

    async def bulk_insert_raw(
        self, articles: list[Any], task_id: uuid.UUID | None = None
    ) -> list[uuid.UUID]:
        return await self._raw_bulk.bulk_insert_raw(articles, task_id)
