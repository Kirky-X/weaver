# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for ArticleRepo."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.db.models import Article
from modules.pipeline.state import PipelineState
from modules.storage.article_repo import ArticleRepo


class TestArticleRepoIntegration:
    """Integration tests for ArticleRepo with PostgreSQL."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    def test_article_repo_initialization(self, article_repo, mock_pool):
        """Test ArticleRepo initializes correctly."""
        assert article_repo._pool is mock_pool

    @pytest.mark.asyncio
    async def test_upsert_creates_new_article(self, article_repo, mock_pool):
        """Test upsert creates a new article when not exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        def add_article(article):
            article.id = uuid.uuid4()

        mock_session.add = MagicMock(side_effect=add_article)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = PipelineState()
        state["raw"] = MagicMock(
            url="https://example.com/new-article",
            source_host="example.com",
            title="New Article",
            body="Article body",
            publish_time=None,
        )
        state["is_news"] = True
        state["category"] = "tech"
        state["language"] = "zh"

        result = await article_repo.upsert(state)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_article(self, article_repo, mock_pool):
        """Test upsert updates existing article."""
        existing_article = MagicMock(spec=Article)
        existing_article.id = uuid.uuid4()
        existing_article.source_url = "https://example.com/existing"
        existing_article.title = "Old Title"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = PipelineState()
        state["raw"] = MagicMock(
            url="https://example.com/existing",
            source_host="example.com",
            title="New Title",
            body="New body",
        )
        state["is_news"] = True
        state["cleaned"] = {"title": "New Title", "body": "New body"}

        result = await article_repo.upsert(state)
        assert result == existing_article.id

    @pytest.mark.asyncio
    async def test_upsert_with_credibility(self, article_repo, mock_pool):
        """Test upsert with credibility data."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        new_id = uuid.uuid4()

        def mock_add(article):
            article.id = new_id

        mock_session.add = MagicMock(side_effect=mock_add)
        mock_session.commit = AsyncMock()

        async def mock_refresh(article):
            article.id = new_id

        mock_session.refresh = AsyncMock(side_effect=mock_refresh)

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = PipelineState()
        state["raw"] = MagicMock(
            url="https://example.com/article",
            source_host="example.com",
            title="Article",
            body="Body",
        )
        state["credibility"] = {
            "score": 0.85,
            "source_credibility": 0.9,
            "cross_verification": 0.8,
            "content_check": 0.85,
        }

        result = await article_repo.upsert(state)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_upsert_with_sentiment(self, article_repo, mock_pool):
        """Test upsert with sentiment data."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        new_id = uuid.uuid4()

        def mock_add(article):
            article.id = new_id

        mock_session.add = MagicMock(side_effect=mock_add)
        mock_session.commit = AsyncMock()

        async def mock_refresh(article):
            article.id = new_id

        mock_session.refresh = AsyncMock(side_effect=mock_refresh)

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = PipelineState()
        state["raw"] = MagicMock(
            url="https://example.com/article",
            source_host="example.com",
            title="Article",
            body="Body",
        )
        state["sentiment"] = {
            "sentiment": "positive",
            "sentiment_score": 0.8,
            "primary_emotion": "optimistic",
        }

        result = await article_repo.upsert(state)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_get_article_by_id(self, article_repo, mock_pool):
        """Test get article by UUID."""
        article_id = uuid.uuid4()
        mock_article = MagicMock(spec=Article)
        mock_article.id = article_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get(article_id)
        assert result.id == article_id

    @pytest.mark.asyncio
    async def test_get_article_by_string_id(self, article_repo, mock_pool):
        """Test get article by string UUID."""
        article_id = uuid.uuid4()
        mock_article = MagicMock(spec=Article)
        mock_article.id = article_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get(str(article_id))
        assert result.id == article_id

    @pytest.mark.asyncio
    async def test_get_pending_neo4j(self, article_repo, mock_pool):
        """Test get pending Neo4j articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_article]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_pending_neo4j(limit=10)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_pending(self, article_repo, mock_pool):
        """Test get pending articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_article]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_pending(limit=10)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_insert_raw_article(self, article_repo, mock_pool):
        """Test insert raw article."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        new_id = uuid.uuid4()

        def mock_add(article):
            article.id = new_id

        mock_session.add = MagicMock(side_effect=mock_add)
        mock_session.commit = AsyncMock()

        async def mock_refresh(article):
            article.id = new_id

        mock_session.refresh = AsyncMock(side_effect=mock_refresh)

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_article = MagicMock()
        mock_article.url = "https://example.com/article"
        mock_article.source_host = "example.com"
        mock_article.title = "Article"
        mock_article.body = "Body"

        result = await article_repo.insert_raw(mock_article)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_insert_raw_existing_url(self, article_repo, mock_pool):
        """Test insert raw article with existing URL returns existing id."""
        existing_id = uuid.uuid4()
        existing_article = MagicMock(spec=Article)
        existing_article.id = existing_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_article = MagicMock()
        mock_article.url = "https://example.com/existing"
        mock_article.source_host = "example.com"
        mock_article.title = "Article"
        mock_article.body = "Body"

        result = await article_repo.insert_raw(mock_article)
        assert result == existing_id

    @pytest.mark.asyncio
    async def test_get_stuck_articles(self, article_repo, mock_pool):
        """Test get stuck articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_article]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_stuck_articles(timeout_minutes=30)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_failed_articles(self, article_repo, mock_pool):
        """Test get failed articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_article]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_failed_articles(max_retries=3)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_mark_failed(self, article_repo, mock_pool):
        """Test mark article as failed."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        await article_repo.mark_failed(article_id, "Test error")
        mock_session.commit.assert_called_once()
