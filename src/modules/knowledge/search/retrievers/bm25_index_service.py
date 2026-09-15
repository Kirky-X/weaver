# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""BM25 index building and maintenance service.

This service manages BM25 index lifecycle:
- Building index from articles table
- Incremental updates for new articles
- Scheduled background rebuilding
- Integration with APScheduler
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select

from core.db import Article, PersistStatus
from core.observability import get_logger
from modules.knowledge.search.retrievers.bm25_retriever import BM25Document, BM25Retriever

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger(__name__)

# Redis key holding the last successful index build time (ISO-8601). Survives
# process restarts so the scheduled job can go straight to incremental mode.
WATERMARK_KEY = "bm25:last_indexed_at"


class BM25IndexService:
    """Service for building and maintaining BM25 index.

    Features:
    - Full index rebuild from articles table
    - Incremental updates for new articles
    - Scheduled background rebuilding via APScheduler
    - Graceful error handling and recovery

    Args:
        relational_pool: Relational database connection pool.
        bm25_retriever: BM25 retriever instance to manage.
        rebuild_interval_seconds: Interval for background rebuild (default 300s).
    """

    def __init__(
        self,
        relational_pool: RelationalPool,
        bm25_retriever: BM25Retriever,
        rebuild_interval_seconds: int = 300,
        cache_client: Any | None = None,
    ) -> None:
        self._relational_pool = relational_pool
        self._retriever = bm25_retriever
        self._rebuild_interval = rebuild_interval_seconds
        self._last_build_time: datetime | None = None
        self._is_building = False
        self._build_count = 0
        self._scheduler_job: Any = None
        # Optional Redis client: persists the watermark across restarts
        self._cache_client = cache_client

    async def build_full_index(self, limit: int | None = None) -> int:
        """Build full BM25 index from all articles.

        Args:
            limit: Optional limit on number of articles to index.

        Returns:
            Number of documents indexed.
        """
        if self._is_building:
            log.warning("bm25_build_already_in_progress")
            return 0

        self._is_building = True
        try:
            return await self._do_full_build(limit)
        finally:
            self._is_building = False

    async def _do_full_build(self, limit: int | None = None) -> int:
        """Run the full build body. Caller owns the ``_is_building`` flag."""
        start_time = datetime.now(UTC)

        try:
            log.info("bm25_build_full_start", limit=limit)

            # Fetch articles from database
            documents = await self._fetch_articles(limit)

            if not documents:
                log.warning("bm25_build_no_articles")
                # Advance the watermark anyway so scheduled incremental runs
                # stop re-attempting a full build on an empty corpus.
                self._last_build_time = datetime.now(UTC)
                await self._write_watermark(self._last_build_time)
                return 0

            # Build index off the event loop (sync tokenization over all docs)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._retriever.index, documents)

            self._last_build_time = datetime.now(UTC)
            self._build_count += 1
            await self._write_watermark(self._last_build_time)

            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            log.info(
                "bm25_build_full_complete",
                documents=len(documents),
                elapsed_seconds=elapsed,
            )

            return len(documents)

        except Exception as exc:
            log.error("bm25_build_full_failed", error=str(exc))
            return 0

    async def incremental_update(self, since: datetime | None = None) -> int:
        """Incrementally update index with new articles.

        Args:
            since: Only include articles updated after this time.
                   If None, uses last build time.

        Returns:
            Number of new documents indexed.
        """
        if self._is_building:
            log.warning("bm25_incremental_build_in_progress")
            return 0

        # Take the flag BEFORE any await: the watermark read below is a
        # suspension point, so two concurrent calls could otherwise both
        # pass the check and run concurrent index mutations.
        self._is_building = True

        try:
            cutoff = since or self._last_build_time or await self._read_watermark()
            if cutoff is None:
                # No previous build, do full build instead (flag already held)
                log.info("bm25_incremental_no_previous_build")
                return await self._do_full_build()

            log.info("bm25_incremental_start", since=cutoff.isoformat())

            # Fetch only new/updated articles
            documents = await self._fetch_articles_since(cutoff)

            if not documents:
                log.info("bm25_incremental_no_new_articles")
                await self._write_watermark(datetime.now(UTC))
                return 0

            # Add to existing index off the event loop
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._retriever.add_documents, documents)

            await self._write_watermark(datetime.now(UTC))
            log.info("bm25_incremental_complete", new_documents=len(documents))
            return len(documents)

        except Exception as exc:
            log.error("bm25_incremental_failed", error=str(exc))
            return 0

        finally:
            self._is_building = False

    async def _fetch_articles(self, limit: int | None = None) -> list[BM25Document]:
        """Fetch articles from database for indexing.

        Args:
            limit: Optional limit on number of articles.

        Returns:
            List of BM25Document objects.
        """
        async with self._relational_pool.session() as session:
            query = (
                select(Article)
                .where(
                    Article.persist_status.in_(list(PersistStatus.completed_statuses())),
                    Article.title.isnot(None),
                    Article.body.isnot(None),
                )
                .order_by(Article.updated_at.desc())
            )

            if limit:
                query = query.limit(limit)

            result = await session.execute(query)
            articles = result.scalars().all()

            documents = []
            for article in articles:
                # Skip articles with empty content
                if not article.title or not article.body:
                    continue

                documents.append(
                    BM25Document(
                        doc_id=str(article.id),
                        title=article.title or "",
                        content=article.body or "",
                        metadata={
                            "source_url": article.source_url,
                            "source_host": article.source_host,
                            "category": article.category,
                            "publish_time": (
                                article.publish_time.isoformat() if article.publish_time else None
                            ),
                            "updated_at": (
                                article.updated_at.isoformat() if article.updated_at else None
                            ),
                        },
                    )
                )

            log.debug("bm25_fetch_articles", count=len(documents))
            return documents

    async def _fetch_articles_since(self, since: datetime) -> list[BM25Document]:
        """Fetch articles updated since a given time.

        Args:
            since: Cutoff time for updated articles.

        Returns:
            List of BM25Document objects.
        """
        async with self._relational_pool.session() as session:
            query = (
                select(Article)
                .where(
                    and_(
                        Article.persist_status.in_(PersistStatus.completed_statuses()),
                        Article.updated_at > since,
                        Article.title.isnot(None),
                        Article.body.isnot(None),
                    )
                )
                .order_by(Article.updated_at.asc())
            )

            result = await session.execute(query)
            articles = result.scalars().all()

            documents = []
            for article in articles:
                if not article.title or not article.body:
                    continue

                documents.append(
                    BM25Document(
                        doc_id=str(article.id),
                        title=article.title or "",
                        content=article.body or "",
                        metadata={
                            "source_url": article.source_url,
                            "source_host": article.source_host,
                            "category": article.category,
                            "publish_time": (
                                article.publish_time.isoformat() if article.publish_time else None
                            ),
                            "updated_at": (
                                article.updated_at.isoformat() if article.updated_at else None
                            ),
                        },
                    )
                )

            return documents

    async def scheduled_rebuild(self) -> int:
        """Scheduled job for maintaining the BM25 index.

        Incremental by default (watermark-based); falls back to a full
        rebuild only when the index is empty or no watermark exists.

        Returns:
            Number of documents indexed.
        """
        log.info("bm25_scheduled_rebuild_start")
        if self._retriever.get_document_count() > 0 or self._last_build_time:
            return await self.incremental_update()
        return await self.build_full_index()

    async def _read_watermark(self) -> datetime | None:
        """Read the last build time from Redis (in-memory value as fallback)."""
        if self._cache_client is not None:
            try:
                raw = await self._cache_client.get(WATERMARK_KEY)
                if raw:
                    return datetime.fromisoformat(raw)
            except Exception as exc:
                log.debug("bm25_watermark_read_failed", error=str(exc))
        return self._last_build_time

    async def _write_watermark(self, moment: datetime) -> None:
        """Persist the last build time to Redis (best-effort)."""
        if self._cache_client is not None:
            try:
                await self._cache_client.set(WATERMARK_KEY, moment.isoformat())
            except Exception as exc:
                log.debug("bm25_watermark_write_failed", error=str(exc))

    def get_stats(self) -> dict[str, Any]:
        """Get service statistics.

        Returns:
            Dictionary with service statistics.
        """
        return {
            "is_building": self._is_building,
            "last_build_time": self._last_build_time.isoformat() if self._last_build_time else None,
            "build_count": self._build_count,
            "document_count": self._retriever.get_document_count(),
            "rebuild_interval_seconds": self._rebuild_interval,
        }
