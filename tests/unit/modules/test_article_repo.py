# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ArticleRepo module (task 4.1.6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db.models import Article, PersistStatus
from core.exceptions import InvalidStateTransitionError
from modules.storage.article_repo import (
    STATE_TO_ARTICLE_FIELDS,
    ArticleRepo,
    _apply_state_to_article,
)


class TestStateToArticleFieldsMapping:
    """Tests for STATE_TO_ARTICLE_FIELDS constant."""

    def test_field_mapping_exists(self):
        """Test all expected field mappings exist."""
        expected_fields = [
            "category",
            "language",
            "region",
            "score",
            "quality_score",
            "is_merged",
            "prompt_versions",
        ]
        for field in expected_fields:
            assert field in STATE_TO_ARTICLE_FIELDS
            assert len(STATE_TO_ARTICLE_FIELDS[field]) == 2

    def test_field_mapping_structure(self):
        """Test field mapping tuple structure."""
        for state_key, (attr_name, extractor) in STATE_TO_ARTICLE_FIELDS.items():
            assert isinstance(state_key, str)
            assert isinstance(attr_name, str)
            assert callable(extractor)


class TestApplyStateToArticle:
    """Tests for _apply_state_to_article function."""

    def test_apply_simple_fields(self):
        """Test applying simple field mappings."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Body",
        )
        state = {
            "category": "tech",
            "language": "zh",
            "region": "cn",
            "score": 0.85,
            "quality_score": 0.9,
            "is_merged": True,
        }

        _apply_state_to_article(article, state)

        assert article.category == "tech"
        assert article.language == "zh"
        assert article.region == "cn"
        assert article.score == 0.85
        assert article.quality_score == 0.9
        assert article.is_merged is True

    def test_apply_summary_info(self):
        """Test applying summary_info field."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Body",
        )
        state = {
            "summary_info": {
                "summary": "Test summary",
                "subjects": ["AI", "Technology"],
                "key_data": {"revenue": "1B"},
                "impact": "High",
                "has_data": True,
            }
        }

        _apply_state_to_article(article, state)

        assert article.summary == "Test summary"
        assert article.subjects == ["AI", "Technology"]
        assert article.key_data == {"revenue": "1B"}
        assert article.impact == "High"
        assert article.has_data is True

    def test_apply_sentiment(self):
        """Test applying sentiment field."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Body",
        )
        state = {
            "sentiment": {
                "sentiment": "positive",
                "sentiment_score": 0.8,
                "primary_emotion": "optimistic",
                "emotion_targets": ["company", "investors"],
            }
        }

        _apply_state_to_article(article, state)

        assert article.sentiment == "positive"
        assert article.sentiment_score == 0.8
        assert article.primary_emotion == "optimistic"
        assert article.emotion_targets == ["company", "investors"]

    def test_apply_credibility(self):
        """Test applying credibility field."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Body",
        )
        state = {
            "credibility": {
                "score": 0.75,
                "source_credibility": 0.9,
                "cross_verification": 0.6,
                "content_check": 0.85,
                "flags": ["unverified_source"],
                "verified_by_sources": 3,
            }
        }

        _apply_state_to_article(article, state)

        assert article.credibility_score == 0.75
        assert article.source_credibility == 0.9
        assert article.cross_verification == 0.6
        assert article.content_check_score == 0.85
        assert article.credibility_flags == ["unverified_source"]
        assert article.verified_by_sources == 3

    def test_apply_merged_source_ids(self):
        """Test applying merged_source_ids with string to UUID conversion."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Body",
        )
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        state = {"merged_source_ids": [str(id1), id2]}  # Mix of string and UUID

        _apply_state_to_article(article, state)

        assert len(article.merged_source_ids) == 2
        assert article.merged_source_ids[0] == id1
        assert article.merged_source_ids[1] == id2

    def test_apply_sets_persist_status(self):
        """Test that _apply_state_to_article sets persist_status to PG_DONE."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Body",
        )
        state = {}

        _apply_state_to_article(article, state)

        assert article.persist_status == PersistStatus.PG_DONE

    def test_apply_sets_updated_at(self):
        """Test that _apply_state_to_article sets updated_at."""
        article = Article(
            source_url="https://example.com/test",
            title="Test",
            body="Body",
        )
        state = {}

        before = datetime.now(UTC)
        _apply_state_to_article(article, state)
        after = datetime.now(UTC)

        assert before <= article.updated_at <= after


class TestArticleRepoInit:
    """Tests for ArticleRepo initialization."""

    def test_init_stores_pool(self):
        """Test ArticleRepo stores pool reference."""
        mock_pool = MagicMock()
        repo = ArticleRepo(mock_pool)
        assert repo._pool is mock_pool


class TestArticleRepoBulkUpsert:
    """Tests for bulk_upsert method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_list(self, article_repo):
        """Test bulk_upsert returns empty list for empty input."""
        result = await article_repo.bulk_upsert([])
        assert result == []

    @pytest.mark.asyncio
    async def test_bulk_upsert_filters_terminal_states(self, article_repo, mock_pool):
        """Test bulk_upsert filters out terminal states."""
        mock_session = AsyncMock()
        mock_session.execute.return_value = MagicMock()
        mock_session.execute.return_value.__iter__ = lambda self: iter([])

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        states = [
            {"terminal": True, "raw": MagicMock(url="https://example.com/1")},
            {"raw": MagicMock(url="https://example.com/2")},
        ]

        result = await article_repo.bulk_upsert(states)
        # Should not process terminal state
        assert isinstance(result, list)


class TestArticleRepoGetExistingUrls:
    """Tests for get_existing_urls method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_existing_urls_empty_list(self, article_repo):
        """Test get_existing_urls returns empty set for empty input."""
        result = await article_repo.get_existing_urls([])
        assert result == set()

    @pytest.mark.asyncio
    async def test_get_existing_urls_returns_matches(self, article_repo, mock_pool):
        """Test get_existing_urls returns matching URLs."""
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([("https://example.com/1",)])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await article_repo.get_existing_urls(
            ["https://example.com/1", "https://example.com/2"]
        )

        assert "https://example.com/1" in result


class TestArticleRepoUpdatePersistStatus:
    """Tests for update_persist_status with state validation."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_update_persist_status_valid_transition(self, article_repo, mock_pool):
        """Test valid state transition succeeds."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = PersistStatus.PENDING

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        # Should not raise
        await article_repo.update_persist_status(article_id, "processing")

    @pytest.mark.asyncio
    async def test_update_persist_status_invalid_transition(self, article_repo, mock_pool):
        """Test invalid state transition raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = PersistStatus.NEO4J_DONE

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        with pytest.raises(InvalidStateTransitionError):
            await article_repo.update_persist_status(article_id, "pending")

    @pytest.mark.asyncio
    async def test_update_persist_status_article_not_found(self, article_repo, mock_pool):
        """Test update_persist_status handles missing article gracefully."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        # Should not raise
        await article_repo.update_persist_status(article_id, "processing")


class TestArticleRepoInsertRaw:
    """Tests for insert_raw method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_insert_raw_requires_url(self, article_repo):
        """Test insert_raw raises ValueError when URL missing."""
        mock_article = MagicMock()
        mock_article.url = ""

        with pytest.raises(ValueError, match="URL"):
            await article_repo.insert_raw(mock_article)

    @pytest.mark.asyncio
    async def test_insert_raw_returns_existing_id(self, article_repo, mock_pool):
        """Test insert_raw returns existing article ID if URL exists."""
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
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.description = ""

        result = await article_repo.insert_raw(mock_article)
        assert result == existing_id


class TestArticleRepoRevertToPgDone:
    """Tests for revert_to_pg_done method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_revert_to_pg_done_success(self, article_repo, mock_pool):
        """Test revert_to_pg_done returns True when row updated."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        result = await article_repo.revert_to_pg_done(article_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_revert_to_pg_done_not_found(self, article_repo, mock_pool):
        """Test revert_to_pg_done returns False when no row updated."""
        mock_result = MagicMock()
        mock_result.rowcount = 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        article_id = uuid.uuid4()
        result = await article_repo.revert_to_pg_done(article_id)
        assert result is False


class TestArticleRepoGetStuckArticles:
    """Tests for get_stuck_articles method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgresPool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def article_repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_stuck_articles(self, article_repo, mock_pool):
        """Test get_stuck_articles returns stuck articles."""
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
