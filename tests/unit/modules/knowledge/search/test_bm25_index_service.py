# Copyright (c) 2026 KirkyX. All Rights Reserved
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


@pytest.fixture
def mock_postgres_pool() -> MagicMock:
    """Create mock PostgreSQL pool."""
    pool = MagicMock()
    pool.session = MagicMock()
    return pool


@pytest.fixture
def mock_bm25_retriever() -> MagicMock:
    """Create mock BM25 retriever."""
    retriever = MagicMock()
    retriever.index = MagicMock()
    retriever.add_documents = MagicMock()
    retriever.get_document_count = MagicMock(return_value=100)
    return retriever


@pytest.fixture
def index_service(
    mock_postgres_pool: MagicMock, mock_bm25_retriever: MagicMock
) -> BM25IndexService:
    """Create BM25IndexService with mocked dependencies."""
    return BM25IndexService(
        postgres_pool=mock_postgres_pool,
        bm25_retriever=mock_bm25_retriever,
        rebuild_interval_seconds=300,
    )


class TestBM25IndexServiceInit:
    """Tests for BM25IndexService initialization."""

    def test_init_default_params(
        self, mock_postgres_pool: MagicMock, mock_bm25_retriever: MagicMock
    ) -> None:
        """Test initialization with default parameters."""
        service = BM25IndexService(
            postgres_pool=mock_postgres_pool,
            bm25_retriever=mock_bm25_retriever,
        )

        assert service._postgres == mock_postgres_pool
        assert service._retriever == mock_bm25_retriever
        assert service._rebuild_interval == 300
        assert service._last_build_time is None
        assert service._is_building is False
        assert service._build_count == 0

    def test_init_custom_params(
        self, mock_postgres_pool: MagicMock, mock_bm25_retriever: MagicMock
    ) -> None:
        """Test initialization with custom parameters."""
        service = BM25IndexService(
            postgres_pool=mock_postgres_pool,
            bm25_retriever=mock_bm25_retriever,
            rebuild_interval_seconds=600,
        )

        assert service._rebuild_interval == 600


class TestBM25IndexServiceBuildFullIndex:
    """Tests for build_full_index method."""

    async def test_build_full_index_success(
        self, index_service: BM25IndexService, mock_bm25_retriever: MagicMock
    ) -> None:
        """Test build_full_index returns number of documents indexed."""
        # Mock _fetch_articles to return documents
        mock_documents = [
            BM25Document(doc_id="1", title="Test 1", content="Content 1"),
            BM25Document(doc_id="2", title="Test 2", content="Content 2"),
        ]

        with patch.object(index_service, "_fetch_articles", return_value=mock_documents):
            result = await index_service.build_full_index()

        assert result == 2
        mock_bm25_retriever.index.assert_called_once_with(mock_documents)
        assert index_service._last_build_time is not None
        assert index_service._build_count == 1

    async def test_build_full_index_with_limit(self, index_service: BM25IndexService) -> None:
        """Test build_full_index respects limit parameter."""
        mock_documents = [
            BM25Document(doc_id="1", title="Test 1", content="Content 1"),
        ]

        with patch.object(
            index_service, "_fetch_articles", return_value=mock_documents
        ) as mock_fetch:
            await index_service.build_full_index(limit=100)

            mock_fetch.assert_called_once_with(100)

    async def test_build_full_index_empty_database(
        self, index_service: BM25IndexService, mock_bm25_retriever: MagicMock
    ) -> None:
        """Test build_full_index with no articles returns 0."""
        with patch.object(index_service, "_fetch_articles", return_value=[]):
            result = await index_service.build_full_index()

        assert result == 0
        mock_bm25_retriever.index.assert_not_called()

    async def test_build_full_index_concurrent_prevented(
        self, index_service: BM25IndexService
    ) -> None:
        """Test concurrent build is prevented."""
        # Set building flag to simulate concurrent build
        index_service._is_building = True

        result = await index_service.build_full_index()

        assert result == 0

    async def test_build_full_index_database_error(
        self,
        index_service: BM25IndexService,
        mock_bm25_retriever: MagicMock,
    ) -> None:
        """Test build_full_index handles database errors."""
        with patch.object(
            index_service,
            "_fetch_articles",
            side_effect=Exception("Database error"),
        ):
            result = await index_service.build_full_index()

        assert result == 0
        # Ensure _is_building is reset in finally block
        assert index_service._is_building is False


class TestBM25IndexServiceIncrementalUpdate:
    """Tests for incremental_update method."""

    async def test_incremental_update_success(
        self, index_service: BM25IndexService, mock_bm25_retriever: MagicMock
    ) -> None:
        """Test incremental update adds new articles."""
        # Set last build time
        index_service._last_build_time = datetime.now(UTC)

        mock_documents = [
            BM25Document(doc_id="3", title="New 1", content="New content 1"),
        ]

        with patch.object(index_service, "_fetch_articles_since", return_value=mock_documents):
            result = await index_service.incremental_update()

        assert result == 1
        mock_bm25_retriever.add_documents.assert_called_once_with(mock_documents)

    async def test_incremental_update_no_new_articles(
        self, index_service: BM25IndexService
    ) -> None:
        """Test incremental update with no new articles."""
        index_service._last_build_time = datetime.now(UTC)

        with patch.object(index_service, "_fetch_articles_since", return_value=[]):
            result = await index_service.incremental_update()

        assert result == 0

    async def test_incremental_update_falls_back_to_full_build(
        self, index_service: BM25IndexService
    ) -> None:
        """Test incremental falls back to full build when no previous build."""
        mock_documents = [
            BM25Document(doc_id="1", title="Test", content="Content"),
        ]

        with patch.object(index_service, "_fetch_articles", return_value=mock_documents):
            result = await index_service.incremental_update()

        assert result == 1

    async def test_incremental_update_blocked_during_build(
        self, index_service: BM25IndexService
    ) -> None:
        """Test incremental update blocked during build."""
        index_service._is_building = True
        index_service._last_build_time = datetime.now(UTC)

        result = await index_service.incremental_update()

        assert result == 0


class TestBM25IndexServiceScheduledRebuild:
    """Tests for scheduled_rebuild method."""

    async def test_scheduled_rebuild_calls_full_build(
        self, index_service: BM25IndexService
    ) -> None:
        """Test scheduled_rebuild invokes build_full_index."""
        mock_documents = [
            BM25Document(doc_id="1", title="Test", content="Content"),
        ]

        with patch.object(index_service, "_fetch_articles", return_value=mock_documents):
            result = await index_service.scheduled_rebuild()

        assert result == 1


class TestBM25IndexServiceSchedulerJob:
    """Tests for create_bm25_scheduler_job function."""

    def test_create_scheduler_job_registers_correctly(
        self, index_service: BM25IndexService
    ) -> None:
        """Test scheduler job is created with correct parameters."""
        mock_scheduler = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "bm25_rebuild_index"
        mock_scheduler.add_job = MagicMock(return_value=mock_job)

        job = create_bm25_scheduler_job(mock_scheduler, index_service)

        assert job.id == "bm25_rebuild_index"
        mock_scheduler.add_job.assert_called_once()

        # Verify call arguments
        call_args = mock_scheduler.add_job.call_args
        assert call_args.kwargs["id"] == "bm25_rebuild_index"
        assert call_args.kwargs["name"] == "BM25 Index Rebuild"
        assert call_args.kwargs["max_instances"] == 1


class TestBM25IndexServiceStats:
    """Tests for get_stats method."""

    def test_get_stats_returns_correct_info(
        self, index_service: BM25IndexService, mock_bm25_retriever: MagicMock
    ) -> None:
        """Test get_stats returns correct statistics."""
        index_service._last_build_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        index_service._build_count = 5
        mock_bm25_retriever.get_document_count = MagicMock(return_value=150)

        stats = index_service.get_stats()

        assert stats["is_building"] is False
        assert stats["last_build_time"] == "2024-01-01T12:00:00+00:00"
        assert stats["build_count"] == 5
        assert stats["document_count"] == 150
        assert stats["rebuild_interval_seconds"] == 300

    def test_get_stats_no_build_time(self, index_service: BM25IndexService) -> None:
        """Test get_stats when no build has occurred."""
        stats = index_service.get_stats()

        assert stats["last_build_time"] is None
        assert stats["build_count"] == 0
