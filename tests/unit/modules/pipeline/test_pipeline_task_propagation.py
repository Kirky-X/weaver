# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for task_id propagation through pipeline components."""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db.models import Article
from modules.collector.models import ArticleRaw
from modules.storage.postgres.article_repo import ArticleRepo


class TestArticleRepoTaskIdInsertion:
    """Tests for task_id handling in ArticleRepo."""

    def test_insert_raw_has_task_id_parameter(self):
        """Test that insert_raw method accepts task_id parameter."""
        sig = inspect.signature(ArticleRepo.insert_raw)
        params = list(sig.parameters.keys())
        assert "task_id" in params, f"Expected 'task_id' in {params}"

    def test_insert_raw_task_id_default_is_none(self):
        """Test that task_id defaults to None for backward compatibility."""
        sig = inspect.signature(ArticleRepo.insert_raw)
        task_id_param = sig.parameters.get("task_id")
        assert task_id_param is not None
        assert task_id_param.default is None

    @pytest.mark.asyncio
    async def test_insert_raw_accepts_task_id_uuid(self):
        """Test insert_raw can be called with a valid UUID task_id."""
        mock_pool = MagicMock()
        repo = ArticleRepo(mock_pool)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        def mock_add(article):
            article.id = uuid.uuid4()

        mock_session.add = MagicMock(side_effect=mock_add)

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article = ArticleRaw(
            url="https://example.com/article",
            title="Test Article",
            body="Test body",
            source="test",
            source_host="example.com",
        )
        task_id = uuid.uuid4()
        result = await repo.insert_raw(article, task_id=task_id)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_insert_raw_without_task_id_backward_compat(self):
        """Test insert_raw works without task_id for backward compatibility."""
        mock_pool = MagicMock()
        repo = ArticleRepo(mock_pool)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        def mock_add(article):
            article.id = uuid.uuid4()

        mock_session.add = MagicMock(side_effect=mock_add)

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article = ArticleRaw(
            url="https://example.com/article-noid",
            title="Test Article",
            body="Test body",
            source="test",
            source_host="example.com",
        )
        result = await repo.insert_raw(article)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_insert_raw_returns_existing_id(self):
        """Test insert_raw returns existing article ID when URL exists."""
        mock_pool = MagicMock()
        repo = ArticleRepo(mock_pool)

        existing_id = uuid.uuid4()
        existing_article = MagicMock(spec=Article)
        existing_article.id = existing_id

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_article
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article = ArticleRaw(
            url="https://example.com/existing",
            title="Existing Article",
            body="Body",
            source="test",
            source_host="example.com",
        )
        result = await repo.insert_raw(article, task_id=uuid.uuid4())
        assert result == existing_id


class TestSourceSchedulerTaskIdPropagation:
    """Tests for task_id propagation in SourceScheduler."""

    def test_scheduler_on_items_callback_accepts_task_id(self):
        """Test that on_items_discovered callback type hints include task_id."""

        from modules.source.scheduler import SourceScheduler

        sig = inspect.signature(SourceScheduler.__init__)
        params = sig.parameters
        assert "on_items_discovered" in params

        callback_hint = params["on_items_discovered"]
        assert "uuid" in str(callback_hint)


class TestDiscoveryProcessorTaskIdPropagation:
    """Tests for task_id propagation in DiscoveryProcessor."""

    def test_on_items_discovered_has_task_id_parameter(self):
        """Test that on_items_discovered method has task_id parameter."""
        from modules.collector.processor import DiscoveryProcessor

        sig = inspect.signature(DiscoveryProcessor.on_items_discovered)
        params = list(sig.parameters.keys())
        assert "task_id" in params, f"Expected 'task_id' in {params}"

    def test_on_items_discovered_task_id_default_is_none(self):
        """Test that task_id defaults to None in on_items_discovered."""
        from modules.collector.processor import DiscoveryProcessor

        sig = inspect.signature(DiscoveryProcessor.on_items_discovered)
        task_id_param = sig.parameters.get("task_id")
        assert task_id_param is not None
        assert task_id_param.default is None

    @pytest.mark.asyncio
    async def test_on_items_discovered_passes_task_id_to_insert_raw(self):
        """Test that on_items_discovered passes task_id to article_repo.insert_raw."""
        from modules.collector.processor import DiscoveryProcessor

        mock_crawler = AsyncMock()
        mock_crawler.crawl_batch.return_value = [
            ArticleRaw(
                url="https://example.com/test",
                title="Test",
                body="Body",
                source="test",
                source_host="example.com",
                publish_time=None,
            )
        ]

        mock_repo = AsyncMock()
        mock_repo.insert_raw.return_value = uuid.uuid4()

        mock_dedup = AsyncMock()
        mock_dedup.dedup.side_effect = lambda x: x

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_repo,
            deduplicator=mock_dedup,
        )

        items = [MagicMock()]
        source = MagicMock()
        source.id = "test_source"

        task_id = uuid.uuid4()
        await processor.on_items_discovered(items, source, max_items=10, task_id=task_id)

        mock_repo.insert_raw.assert_called()
        call_kwargs = mock_repo.insert_raw.call_args
        assert call_kwargs.kwargs.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_on_items_discovered_works_without_task_id(self):
        """Test backward compatibility - on_items_discovered works without task_id."""
        from modules.collector.processor import DiscoveryProcessor

        mock_crawler = AsyncMock()
        mock_crawler.crawl_batch.return_value = [
            ArticleRaw(
                url="https://example.com/test2",
                title="Test",
                body="Body",
                source="test",
                source_host="example.com",
                publish_time=None,
            )
        ]

        mock_repo = AsyncMock()
        mock_repo.insert_raw.return_value = uuid.uuid4()

        mock_dedup = AsyncMock()
        mock_dedup.dedup.side_effect = lambda x: x

        processor = DiscoveryProcessor(
            crawler=mock_crawler,
            article_repo=mock_repo,
            deduplicator=mock_dedup,
        )

        items = [MagicMock()]
        source = MagicMock()
        source.id = "test_source"

        await processor.on_items_discovered(items, source, max_items=10)

        mock_repo.insert_raw.assert_called()
        call_kwargs = mock_repo.insert_raw.call_args
        assert call_kwargs.kwargs.get("task_id") is None
