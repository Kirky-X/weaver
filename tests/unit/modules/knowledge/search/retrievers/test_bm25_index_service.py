# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for BM25IndexService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.knowledge.search.retrievers.bm25_index_service import (
    BM25IndexService,
    create_bm25_scheduler_job,
)
from modules.knowledge.search.retrievers.bm25_retriever import BM25Document


def _make_mock_article(
    id=1,
    title="Test Article",
    body="Content",
    persist_status=None,
    source_url=None,
    source_host=None,
    category=None,
    publish_time=None,
    updated_at=None,
):
    """Create a mock Article ORM object."""
    from core.db import PersistStatus

    article = MagicMock()
    article.id = id
    article.title = title
    article.body = body
    article.persist_status = persist_status or PersistStatus.PG_DONE
    article.source_url = source_url
    article.source_host = source_host
    article.category = category
    article.publish_time = publish_time
    article.updated_at = updated_at or datetime.now(UTC)
    return article


class TestBM25IndexServiceInit:
    """Tests for initialization."""

    def test_default_params(self) -> None:
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        assert service._rebuild_interval == 300
        assert service._is_building is False
        assert service._build_count == 0


class TestBuildFullIndex:
    """Tests for build_full_index."""

    @pytest.mark.asyncio
    async def test_already_building(self) -> None:
        """Returns 0 when already building."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._is_building = True
        result = await service.build_full_index()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_articles(self) -> None:
        """Returns 0 when no articles found."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._fetch_articles = AsyncMock(return_value=[])
        result = await service.build_full_index()
        assert result == 0

    @pytest.mark.asyncio
    async def test_successful_build(self) -> None:
        """Builds index with fetched articles."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        docs = [BM25Document(doc_id="1", title="T", content="C")]
        service = BM25IndexService(mock_pg, mock_retriever)
        service._fetch_articles = AsyncMock(return_value=docs)
        result = await service.build_full_index()
        assert result == 1
        assert service._build_count == 1
        assert service._last_build_time is not None
        mock_retriever.index.assert_called_once_with(docs)

    @pytest.mark.asyncio
    async def test_exception_returns_zero(self) -> None:
        """Exception during build returns 0."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._fetch_articles = AsyncMock(side_effect=Exception("DB error"))
        result = await service.build_full_index()
        assert result == 0
        assert service._is_building is False


class TestIncrementalUpdate:
    """Tests for incremental_update."""

    @pytest.mark.asyncio
    async def test_no_previous_build(self) -> None:
        """No previous build triggers full build."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._fetch_articles = AsyncMock(
            return_value=[
                BM25Document(doc_id="1", title="T", content="C"),
            ]
        )
        result = await service.incremental_update()
        assert result == 1

    @pytest.mark.asyncio
    async def test_already_building(self) -> None:
        """Returns 0 when already building."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._is_building = True
        result = await service.incremental_update(since=datetime.now(UTC))
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_new_articles(self) -> None:
        """Returns 0 when no new articles."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._last_build_time = datetime.now(UTC)
        service._fetch_articles_since = AsyncMock(return_value=[])
        result = await service.incremental_update()
        assert result == 0

    @pytest.mark.asyncio
    async def test_with_new_articles(self) -> None:
        """Incrementally adds new articles."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._last_build_time = datetime.now(UTC)
        docs = [BM25Document(doc_id="2", title="New", content="Content")]
        service._fetch_articles_since = AsyncMock(return_value=docs)
        result = await service.incremental_update()
        assert result == 1
        mock_retriever.add_documents.assert_called_once_with(docs)

    @pytest.mark.asyncio
    async def test_exception_returns_zero(self) -> None:
        """Exception during incremental returns 0."""
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._last_build_time = datetime.now(UTC)
        service._fetch_articles_since = AsyncMock(side_effect=Exception("error"))
        result = await service.incremental_update()
        assert result == 0
        assert service._is_building is False


class TestFetchArticles:
    """Tests for _fetch_articles."""

    @pytest.mark.asyncio
    async def test_fetch_with_articles(self) -> None:
        """Fetches and converts articles."""
        mock_article = _make_mock_article(id=42, title="Test", body="Body")
        mock_article.updated_at = datetime.now(UTC)

        mock_pg = MagicMock()
        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = [mock_article]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result_mock)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pg.session = MagicMock(return_value=ctx)

        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        docs = await service._fetch_articles()
        assert len(docs) == 1
        assert docs[0].doc_id == "42"

    @pytest.mark.asyncio
    async def test_fetch_with_limit(self) -> None:
        """Applies limit to query."""
        mock_pg = MagicMock()
        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result_mock)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pg.session = MagicMock(return_value=ctx)

        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        docs = await service._fetch_articles(limit=10)
        assert docs == []


class TestFetchArticlesSince:
    """Tests for _fetch_articles_since."""

    @pytest.mark.asyncio
    async def test_fetch_since(self) -> None:
        mock_article = _make_mock_article(title="New", body="Content")
        mock_article.updated_at = datetime.now(UTC)

        mock_pg = MagicMock()
        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = [mock_article]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result_mock)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pg.session = MagicMock(return_value=ctx)

        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        docs = await service._fetch_articles_since(datetime.now(UTC))
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_skips_empty_content(self) -> None:
        """Articles with empty title/body are skipped."""
        mock_article = _make_mock_article(title="", body="")

        mock_pg = MagicMock()
        session = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = [mock_article]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars
        session.execute = AsyncMock(return_value=result_mock)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pg.session = MagicMock(return_value=ctx)

        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        docs = await service._fetch_articles_since(datetime.now(UTC))
        assert docs == []


class TestScheduledRebuild:
    """Tests for scheduled_rebuild."""

    @pytest.mark.asyncio
    async def test_scheduled_rebuild(self) -> None:
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        mock_retriever.get_document_count.return_value = 0  # empty index -> full build
        service = BM25IndexService(mock_pg, mock_retriever)
        service._fetch_articles = AsyncMock(
            return_value=[
                BM25Document(doc_id="1", title="T", content="C"),
            ]
        )
        result = await service.scheduled_rebuild()
        assert result == 1


class TestGetStats:
    """Tests for get_stats."""

    def test_stats(self) -> None:
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        mock_retriever.get_document_count.return_value = 100
        service = BM25IndexService(mock_pg, mock_retriever)
        stats = service.get_stats()
        assert stats["is_building"] is False
        assert stats["build_count"] == 0
        assert stats["document_count"] == 100
        assert stats["rebuild_interval_seconds"] == 300

    def test_stats_with_build_time(self) -> None:
        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)
        service._last_build_time = datetime.now(UTC)
        stats = service.get_stats()
        assert stats["last_build_time"] is not None


class TestCreateBm25SchedulerJob:
    """Tests for create_bm25_scheduler_job."""

    def test_creates_job(self) -> None:
        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "bm25_rebuild_index"
        mock_scheduler.add_job.return_value = mock_job

        mock_pg = MagicMock()
        mock_retriever = MagicMock()
        service = BM25IndexService(mock_pg, mock_retriever)

        job = create_bm25_scheduler_job(mock_scheduler, service)
        assert job.id == "bm25_rebuild_index"
        mock_scheduler.add_job.assert_called_once()


# ────────────────────────────────────────────────────────────────────────────
# T014: incremental-by-default scheduling, watermark persistence, executor offload
# ────────────────────────────────────────────────────────────────────────────

from datetime import timedelta

from modules.knowledge.search.retrievers.bm25_index_service import (
    WATERMARK_KEY,
)


def _t014_service(cache_client=None):
    retriever = MagicMock()
    retriever.get_document_count = MagicMock(return_value=100)
    retriever.index = MagicMock(return_value=None)
    retriever.add_documents = MagicMock(return_value=None)
    pool = MagicMock()
    service = BM25IndexService(
        relational_pool=pool, bm25_retriever=retriever, cache_client=cache_client
    )
    return service, retriever


class TestScheduledRebuildIncremental:
    """scheduled_rebuild prefers incremental via watermark; full only when empty."""

    @pytest.mark.asyncio
    async def test_incremental_by_default_with_watermark(self):
        cache = MagicMock()
        cache.get = AsyncMock(return_value=(datetime.now(UTC) - timedelta(hours=1)).isoformat())
        cache.set = AsyncMock()
        service, retriever = _t014_service(cache_client=cache)

        with (
            patch.object(
                service,
                "_fetch_articles_since",
                new=AsyncMock(
                    return_value=[BM25Document(doc_id="1", title="t", content="c", metadata={})]
                ),
            ),
            patch.object(service, "_fetch_articles", new=AsyncMock(return_value=[])),
        ):
            count = await service.scheduled_rebuild()

        assert count == 1
        retriever.add_documents.assert_called_once()
        retriever.index.assert_not_called()
        cache.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_full_rebuild_when_index_empty(self):
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()
        service, retriever = _t014_service(cache_client=cache)
        retriever.get_document_count = MagicMock(return_value=0)

        with patch.object(
            service,
            "_fetch_articles",
            new=AsyncMock(
                return_value=[BM25Document(doc_id="1", title="t", content="c", metadata={})]
            ),
        ):
            count = await service.scheduled_rebuild()

        assert count == 1
        retriever.index.assert_called_once()
        retriever.add_documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_watermark_and_no_cache_falls_back_to_full(self):
        service, retriever = _t014_service(cache_client=None)

        with patch.object(
            service,
            "_fetch_articles",
            new=AsyncMock(
                return_value=[BM25Document(doc_id="1", title="t", content="c", metadata={})]
            ),
        ):
            await service.scheduled_rebuild()

        retriever.index.assert_called_once()

    @pytest.mark.asyncio
    async def test_incremental_failure_does_not_advance_watermark(self):
        cache = MagicMock()
        cache.get = AsyncMock(return_value=datetime.now(UTC).isoformat())
        cache.set = AsyncMock()
        service, _retriever = _t014_service(cache_client=cache)

        with patch.object(
            service, "_fetch_articles_since", new=AsyncMock(side_effect=RuntimeError("db down"))
        ):
            await service.incremental_update(since=datetime.now(UTC))

        cache.set.assert_not_awaited()


class TestExecutorOffload:
    @pytest.mark.asyncio
    async def test_full_index_build_off_event_loop(self):
        import threading

        service, retriever = _t014_service()
        threads: list[str] = []

        def spy_index(documents):
            threads.append(threading.current_thread().name)

        retriever.index.side_effect = spy_index

        with patch.object(
            service,
            "_fetch_articles",
            new=AsyncMock(
                return_value=[BM25Document(doc_id="1", title="t", content="c", metadata={})]
            ),
        ):
            await service.build_full_index()

        assert threads
        assert all(name != threading.main_thread().name for name in threads)

    @pytest.mark.asyncio
    async def test_incremental_add_off_event_loop(self):
        import threading

        service, retriever = _t014_service()
        threads: list[str] = []

        def spy_add(documents):
            threads.append(threading.current_thread().name)

        retriever.add_documents.side_effect = spy_add

        with patch.object(
            service,
            "_fetch_articles_since",
            new=AsyncMock(
                return_value=[BM25Document(doc_id="1", title="t", content="c", metadata={})]
            ),
        ):
            await service.incremental_update(since=datetime.now(UTC) - timedelta(hours=1))

        assert threads
        assert all(name != threading.main_thread().name for name in threads)


class TestWatermarkPersistence:
    @pytest.mark.asyncio
    async def test_watermark_survives_restart(self):
        cache = MagicMock()
        cutoff = datetime.now(UTC) - timedelta(hours=2)
        cache.get = AsyncMock(return_value=cutoff.isoformat())
        cache.set = AsyncMock()

        service, retriever = _t014_service(cache_client=cache)
        captured_since: dict = {}

        async def fake_fetch(since):
            captured_since["since"] = since
            return []

        with patch.object(service, "_fetch_articles_since", new=fake_fetch):
            await service.scheduled_rebuild()

        assert captured_since["since"] == cutoff
        retriever.index.assert_not_called()

    def test_watermark_key_name(self):
        assert WATERMARK_KEY == "bm25:last_indexed_at"
