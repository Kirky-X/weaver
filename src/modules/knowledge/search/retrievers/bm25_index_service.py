# Copyright (c) 2026 KirkyX. All Rights Reserved
"""BM25 index building and maintenance service.

This service manages BM25 index lifecycle:
- Building index from articles table
- Incremental updates for new articles
- Scheduled background rebuilding
- Integration with APScheduler
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, select

from core.db.models import Article, PersistStatus
from core.observability.logging import get_logger
from modules.knowledge.search.retrievers.bm25_retriever import BM25Document, BM25Retriever

if TYPE_CHECKING:
    from core.protocols import RelationalPool

log = get_logger("bm25_index_service")


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
    ) -> None:
        self._relational_pool = relational_pool
        self._retriever = bm25_retriever
        self._rebuild_interval = rebuild_interval_seconds
        self._last_build_time: datetime | None = None
        self._is_building = False
        self._build_count = 0
        self._scheduler_job: Any = None

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
        start_time = datetime.now(UTC)

        try:
            log.info("bm25_build_full_start", limit=limit)

            # Fetch articles from database
            documents = await self._fetch_articles(limit)

            if not documents:
                log.warning("bm25_build_no_articles")
                return 0

            # Build index
            self._retriever.index(documents)

            self._last_build_time = datetime.now(UTC)
            self._build_count += 1

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

        finally:
            self._is_building = False

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

        cutoff = since or self._last_build_time
        if cutoff is None:
            # No previous build, do full build instead
            log.info("bm25_incremental_no_previous_build")
            return await self.build_full_index()

        self._is_building = True

        try:
            log.info("bm25_incremental_start", since=cutoff.isoformat())

            # Fetch only new/updated articles
            documents = await self._fetch_articles_since(cutoff)

            if not documents:
                log.info("bm25_incremental_no_new_articles")
                return 0

            # Add to existing index
            self._retriever.add_documents(documents)

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
                    Article.persist_status.in_(
                        [
                            PersistStatus.PG_DONE,
                            PersistStatus.NEO4J_DONE,
                        ]
                    ),
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
                        Article.persist_status.in_(
                            [
                                PersistStatus.PG_DONE,
                                PersistStatus.NEO4J_DONE,
                            ]
                        ),
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
        """Scheduled job for rebuilding BM25 index.

        This method is called by APScheduler at configured intervals.
        It performs a full rebuild to ensure index consistency.

        Returns:
            Number of documents indexed.
        """
        log.info("bm25_scheduled_rebuild_start")
        return await self.build_full_index()

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


def create_bm25_scheduler_job(
    scheduler: Any,
    index_service: BM25IndexService,
) -> Any:
    """Create and register BM25 rebuild job with APScheduler.

    Args:
        scheduler: APScheduler AsyncScheduler instance.
        index_service: BM25IndexService instance.

    Returns:
        The scheduled job.
    """
    from apscheduler.triggers.interval import IntervalTrigger

    # Create interval trigger
    trigger = IntervalTrigger(seconds=index_service._rebuild_interval)

    # Add job to scheduler
    job = scheduler.add_job(
        index_service.scheduled_rebuild,
        trigger=trigger,
        id="bm25_rebuild_index",
        name="BM25 Index Rebuild",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping runs
    )

    log.info(
        "bm25_scheduler_job_added",
        interval_seconds=index_service._rebuild_interval,
        job_id=job.id,
    )

    return job
