# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for articles endpoints — beyond the model/basic tests in test_api.py."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_mock_article(
    article_id: uuid.UUID | str | None = None,
    title: str = "Test Article",
    source_host: str = "example.com",
    score: float | None = 0.8,
    **overrides,
) -> MagicMock:
    """Create a mock Article with sensible defaults."""
    if article_id is None:
        article_id = uuid.uuid4()
    if isinstance(article_id, str):
        article_id = uuid.UUID(article_id)

    article = MagicMock()
    article.id = article_id
    article.source_url = f"https://{source_host}/article"
    article.source_host = source_host
    article.is_news = True
    article.title = title
    article.body = "Test body content"
    article.category = None
    article.language = "zh"
    article.region = None
    article.summary = None
    article.event_time = None
    article.subjects = None
    article.key_data = None
    article.impact = None
    article.score = score
    article.sentiment = None
    article.sentiment_score = None
    article.primary_emotion = None
    article.credibility_score = None
    article.source_credibility = None
    article.cross_verification = None
    article.content_check_score = None
    article.publish_time = None
    article.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    article.updated_at = datetime(2024, 1, 2, tzinfo=timezone.utc)
    for k, v in overrides.items():
        setattr(article, k, v)
    return article


def _make_mock_request() -> MagicMock:
    """Create a mock Starlette request for rate-limited endpoints."""
    from starlette.requests import Request

    mock_req = MagicMock(spec=Request)
    mock_req.client = MagicMock()
    mock_req.client.host = "127.0.0.1"
    return mock_req


def _make_mock_pool(articles: list[MagicMock], total: int | None = None) -> MagicMock:
    """Create a mock PostgresPool that returns the given articles."""
    if total is None:
        total = len(articles)

    count_result = MagicMock()
    count_result.scalar.return_value = total

    articles_result = MagicMock()
    articles_result.scalars.return_value.all.return_value = articles

    session = AsyncMock()
    # First call = count, second call = articles
    session.execute = AsyncMock(side_effect=[count_result, articles_result])

    pool = MagicMock()
    pool.session.return_value.__aenter__ = AsyncMock(return_value=session)
    pool.session.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


class TestListArticlesPagination:
    """Tests for pagination in GET /articles."""

    @pytest.mark.asyncio
    async def test_default_page_is_1(self):
        """Test default page number is 1."""
        from api.endpoints.articles import list_articles

        article = _make_mock_article()
        pool = _make_mock_pool([article], total=1)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=20,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert result.data.page == 1

    @pytest.mark.asyncio
    async def test_custom_page_and_page_size(self):
        """Test custom page and page_size parameters."""
        from api.endpoints.articles import list_articles

        articles = [_make_mock_article(title=f"Article {i}") for i in range(10)]
        pool = _make_mock_pool(articles, total=50)

        result = await list_articles(
            request=_make_mock_request(),
            page=3,
            page_size=10,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert result.data.page == 3
        assert result.data.page_size == 10

    @pytest.mark.asyncio
    async def test_total_pages_calculation(self):
        """Test total_pages is computed correctly."""
        from api.endpoints.articles import list_articles

        articles = [_make_mock_article() for _ in range(10)]
        pool = _make_mock_pool(articles, total=25)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=10,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        # (25 + 10 - 1) // 10 = 3
        assert result.data.total_pages == 3
        assert result.data.total == 25

    @pytest.mark.asyncio
    async def test_page_out_of_range_returns_empty_items(self):
        """Test requesting a page beyond available data returns empty items."""
        from api.endpoints.articles import list_articles

        # Pool returns 0 articles for this page
        pool = _make_mock_pool([], total=5)

        result = await list_articles(
            request=_make_mock_request(),
            page=100,
            page_size=10,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert result.data.items == []
        assert result.data.page == 100


class TestListArticlesFiltering:
    """Tests for filtering in GET /articles."""

    @pytest.mark.asyncio
    async def test_filter_by_source_host(self):
        """Test filtering articles by source_host."""
        from api.endpoints.articles import list_articles

        articles = [_make_mock_article(source_host="news.example.com")]
        pool = _make_mock_pool(articles, total=1)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=20,
            category=None,
            source_host="news.example.com",
            min_score=None,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert len(result.data.items) == 1
        assert result.data.items[0]["source_host"] == "news.example.com"

    @pytest.mark.asyncio
    async def test_filter_by_min_score(self):
        """Test filtering articles by minimum score."""
        from api.endpoints.articles import list_articles

        article = _make_mock_article(score=0.85)
        pool = _make_mock_pool([article], total=1)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=20,
            category=None,
            source_host=None,
            min_score=0.8,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert len(result.data.items) == 1

    @pytest.mark.asyncio
    async def test_combined_filters(self):
        """Test using multiple filters simultaneously."""
        from api.endpoints.articles import list_articles

        article = _make_mock_article(source_host="tech.example.com", score=0.9)
        pool = _make_mock_pool([article], total=1)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=20,
            category=None,
            source_host="tech.example.com",
            min_score=0.8,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert len(result.data.items) == 1


class TestListArticlesSorting:
    """Tests for sorting in GET /articles."""

    @pytest.mark.asyncio
    async def test_sort_by_created_at_ascending(self):
        """Test sorting by created_at in ascending order."""
        from api.endpoints.articles import list_articles

        articles = [_make_mock_article()]
        pool = _make_mock_pool(articles, total=1)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=20,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="created_at",
            sort_order="asc",
            _="test-key",
            pool=pool,
        )
        # If the query ran without error, sorting is accepted
        assert result.data.page == 1

    @pytest.mark.asyncio
    async def test_sort_by_score_descending(self):
        """Test sorting by score in descending order."""
        from api.endpoints.articles import list_articles

        articles = [_make_mock_article(score=0.9)]
        pool = _make_mock_pool(articles, total=1)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=20,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="score",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert result.data.page == 1


class TestListArticlesEmptyResults:
    """Tests for empty result handling in GET /articles."""

    @pytest.mark.asyncio
    async def test_no_articles_returns_empty_list(self):
        """Test that zero articles returns an empty items list."""
        from api.endpoints.articles import list_articles

        pool = _make_mock_pool([], total=0)

        result = await list_articles(
            request=_make_mock_request(),
            page=1,
            page_size=20,
            category=None,
            source_host=None,
            min_score=None,
            min_credibility=None,
            sort_by="publish_time",
            sort_order="desc",
            _="test-key",
            pool=pool,
        )
        assert result.data.items == []
        assert result.data.total == 0
        assert result.data.total_pages == 0


class TestGetArticleDetail:
    """Tests for GET /articles/{article_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_article_detail_returns_title_and_body(self):
        """Test that get_article returns full article detail."""
        from api.endpoints.articles import get_article

        article = _make_mock_article(
            article_id="12345678-1234-5678-1234-567812345678",
            title="Detailed Article",
            body="Full article body content",
        )

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = article

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await get_article(
            article_id="12345678-1234-5678-1234-567812345678",
            _="test-key",
            pool=pool,
        )
        assert result.data.title == "Detailed Article"
        assert result.data.body == "Full article body content"

    @pytest.mark.asyncio
    async def test_get_article_invalid_uuid_returns_400(self):
        """Test that invalid UUID format returns 400."""
        from api.endpoints.articles import get_article

        pool = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_article(
                article_id="not-a-valid-uuid",
                _="test-key",
                pool=pool,
            )
        assert exc_info.value.status_code == 400
        assert "Invalid article ID format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_article_not_found_returns_404(self):
        """Test that non-existent article ID returns 404."""
        from api.endpoints.articles import get_article

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_article(
                article_id="12345678-1234-5678-1234-567812345678",
                _="test-key",
                pool=pool,
            )
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail


class TestArticlesEndpointHTTPLevel:
    """HTTP-level tests for articles endpoints via TestClient."""

    def test_get_articles_requires_authentication(self):
        """Test that GET /articles requires X-API-Key header."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.endpoints.articles import router, set_postgres_pool

        app = FastAPI()
        app.include_router(router)
        set_postgres_pool(MagicMock())

        with TestClient(app) as client:
            response = client.get("/articles")
            assert response.status_code == 401

    def test_get_article_detail_requires_authentication(self):
        """Test that GET /articles/{id} requires X-API-Key header."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.endpoints.articles import router, set_postgres_pool

        app = FastAPI()
        app.include_router(router)
        set_postgres_pool(MagicMock())

        with TestClient(app) as client:
            response = client.get(f"/articles/{uuid.uuid4()}")
            assert response.status_code == 401
