"""Integration tests for ArticleRepo."""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from modules.storage.article_repo import ArticleRepo
from core.db.models import Article, PersistStatus


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
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        def add_article(article):
            article.id = uuid.uuid4()

        mock_session.add = MagicMock(side_effect=add_article)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = {
            "raw": MagicMock(
                url="https://example.com/new-article",
                source_host="example.com",
                title="New Article",
                body="Article body",
                publish_time=None,
            ),
            "is_news": True,
            "category": "tech",
            "language": "zh",
        }

        result = await article_repo.upsert(state)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_article(self, article_repo, mock_pool):
        """Test upsert updates existing article."""
        existing_article = MagicMock(spec=Article)
        existing_article.id = uuid.uuid4()
        existing_article.source_url = "https://example.com/existing"
        existing_article.title = "Old Title"

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = existing_article
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = {
            "raw": MagicMock(
                url="https://example.com/existing",
                source_host="example.com",
                title="Old Title",
                body="Old body",
                publish_time=None,
            ),
            "category": "finance",
            "score": 0.85,
        }

        result = await article_repo.upsert(state)
        assert existing_article.category == "finance"
        assert existing_article.score == 0.85

    @pytest.mark.asyncio
    async def test_upsert_with_credibility(self, article_repo, mock_pool):
        """Test upsert handles credibility data."""
        existing_article = MagicMock(spec=Article)
        existing_article.id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = existing_article
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = {
            "raw": MagicMock(
                url="https://example.com/article",
                source_host="example.com",
                title="Test",
                body="Body",
                publish_time=None,
            ),
            "credibility": {
                "score": 0.9,
                "source_credibility": 0.85,
                "cross_verification": 0.8,
                "content_check": 0.95,
                "flags": ["verified"],
                "verified_by_sources": 3,
            },
        }

        await article_repo.upsert(state)
        assert existing_article.credibility_score == 0.9
        assert existing_article.source_credibility == 0.85

    @pytest.mark.asyncio
    async def test_upsert_with_sentiment(self, article_repo, mock_pool):
        """Test upsert handles sentiment data."""
        existing_article = MagicMock(spec=Article)
        existing_article.id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = existing_article
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        state = {
            "raw": MagicMock(
                url="https://example.com/article",
                source_host="example.com",
                title="Test",
                body="Body",
                publish_time=None,
            ),
            "sentiment": {
                "sentiment": "positive",
                "sentiment_score": 0.75,
                "primary_emotion": "joy",
                "emotion_targets": ["target1"],
            },
        }

        await article_repo.upsert(state)
        assert existing_article.sentiment == "positive"
        assert existing_article.sentiment_score == 0.75

    @pytest.mark.asyncio
    async def test_get_article_by_id(self, article_repo, mock_pool):
        """Test get article by ID."""
        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_article

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get(mock_article.id)
        assert result is mock_article

    @pytest.mark.asyncio
    async def test_get_article_by_string_id(self, article_repo, mock_pool):
        """Test get article by string ID."""
        article_id = uuid.uuid4()
        mock_article = MagicMock(spec=Article)
        mock_article.id = article_id

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_article

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get(str(article_id))
        assert result is mock_article

    @pytest.mark.asyncio
    async def test_get_existing_urls(self, article_repo, mock_pool):
        """Test get existing URLs."""
        mock_session = AsyncMock()
        mock_session.execute.return_value = [
            ("https://example.com/1",),
            ("https://example.com/2",),
        ]

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

        result = await article_repo.get_existing_urls(urls)
        assert "https://example.com/1" in result
        assert "https://example.com/2" in result

    @pytest.mark.asyncio
    async def test_get_existing_urls_empty(self, article_repo, mock_pool):
        """Test get existing URLs with empty list."""
        result = await article_repo.get_existing_urls([])
        assert result == set()

    @pytest.mark.asyncio
    async def test_update_persist_status(self, article_repo, mock_pool):
        """Test update persist status."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        await article_repo.update_persist_status(article_id, "pg_done")
        mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_update_credibility(self, article_repo, mock_pool):
        """Test update credibility."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        await article_repo.update_credibility(
            article_id=str(article_id),
            credibility_score=0.9,
            cross_verification=0.8,
            verified_by_sources=3,
        )
        mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_get_pending_neo4j(self, article_repo, mock_pool):
        """Test get pending Neo4j articles."""
        mock_articles = [MagicMock(spec=Article), MagicMock(spec=Article)]

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = mock_articles

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_pending_neo4j(limit=10)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_pending(self, article_repo, mock_pool):
        """Test get pending articles."""
        mock_articles = [MagicMock(spec=Article)]

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = mock_articles

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_pending(limit=50)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_insert_raw_article(self, article_repo, mock_pool):
        """Test insert raw article."""
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_session.commit = AsyncMock()

        mock_article = MagicMock()
        mock_article.id = uuid.uuid4()

        def add_article(article):
            article.id = uuid.uuid4()

        mock_session.add = MagicMock(side_effect=add_article)

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        from modules.collector.models import ArticleRaw

        raw = ArticleRaw(
            url="https://example.com/raw-article",
            title="Raw Article",
            body="Raw body content",
            source="example.com",
            publish_time=datetime.now(timezone.utc),
            source_host="example.com",
        )

        result = await article_repo.insert_raw(raw)
        assert isinstance(result, uuid.UUID)

    @pytest.mark.asyncio
    async def test_insert_raw_existing_url(self, article_repo, mock_pool):
        """Test insert raw returns existing ID for duplicate URL."""
        existing_id = uuid.uuid4()
        existing_article = MagicMock(spec=Article)
        existing_article.id = existing_id

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = existing_article

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        from modules.collector.models import ArticleRaw

        raw = ArticleRaw(
            url="https://example.com/existing",
            title="Existing",
            body="Body",
            source="example.com",
            publish_time=None,
            source_host="example.com",
        )

        result = await article_repo.insert_raw(raw)
        assert result == existing_id

    @pytest.mark.asyncio
    async def test_insert_raw_missing_url(self, article_repo, mock_pool):
        """Test insert raw raises error for missing URL."""
        from modules.collector.models import ArticleRaw

        raw = ArticleRaw(
            url="",
            title="No URL",
            body="Body",
            source="example.com",
            publish_time=None,
            source_host="example.com",
        )

        with pytest.raises(ValueError, match="URL is required"):
            await article_repo.insert_raw(raw)

    @pytest.mark.asyncio
    async def test_get_stuck_articles(self, article_repo, mock_pool):
        """Test get stuck articles."""
        mock_articles = [MagicMock(spec=Article)]

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = mock_articles

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_stuck_articles(timeout_minutes=30)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_failed_articles(self, article_repo, mock_pool):
        """Test get failed articles."""
        mock_articles = [MagicMock(spec=Article)]

        mock_session = AsyncMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = mock_articles

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_failed_articles(max_retries=3)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_mark_failed(self, article_repo, mock_pool):
        """Test mark article as failed."""
        mock_session = AsyncMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = 0
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        await article_repo.mark_failed(article_id, "Test error", increment_retry=True)
        mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_mark_processing(self, article_repo, mock_pool):
        """Test mark article as processing."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        await article_repo.mark_processing(article_id, "classify")
        mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_update_processing_stage(self, article_repo, mock_pool):
        """Test update processing stage."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        await article_repo.update_processing_stage(article_id, "analyze")
        mock_session.execute.assert_called()
