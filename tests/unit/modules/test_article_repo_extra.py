# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ArticleRepo additional methods to improve coverage."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from core.db.models import Article, PersistStatus
from core.exceptions import InvalidStateTransitionError
from modules.storage.postgres.article_repo import (
    ArticleRepo,
    is_enrichment_complete,
)


class TestIsEnrichmentComplete:
    """Tests for is_enrichment_complete function."""

    def test_complete_enrichment(self):
        """Test with all required fields present."""
        state = {
            "category": "tech",
            "score": 0.85,
            "credibility": {"score": 0.9},
            "summary_info": {"summary": "Test summary"},
            "quality_score": 0.8,
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is True
        assert missing == []

    def test_missing_category(self):
        """Test with missing category."""
        state = {
            "score": 0.85,
            "credibility": {"score": 0.9},
            "summary_info": {"summary": "Test summary"},
            "quality_score": 0.8,
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert "category" in missing

    def test_missing_score(self):
        """Test with missing score."""
        state = {
            "category": "tech",
            "credibility": {"score": 0.9},
            "summary_info": {"summary": "Test summary"},
            "quality_score": 0.8,
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert "score" in missing

    def test_missing_credibility_score(self):
        """Test with missing credibility score."""
        state = {
            "category": "tech",
            "score": 0.85,
            "credibility": {},  # No score
            "summary_info": {"summary": "Test summary"},
            "quality_score": 0.8,
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert "credibility_score" in missing

    def test_missing_credibility_object(self):
        """Test with missing credibility object."""
        state = {
            "category": "tech",
            "score": 0.85,
            "summary_info": {"summary": "Test summary"},
            "quality_score": 0.8,
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert "credibility_score" in missing

    def test_missing_summary(self):
        """Test with missing summary."""
        state = {
            "category": "tech",
            "score": 0.85,
            "credibility": {"score": 0.9},
            "summary_info": {},  # No summary
            "quality_score": 0.8,
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert "summary" in missing

    def test_missing_summary_info_object(self):
        """Test with missing summary_info object."""
        state = {
            "category": "tech",
            "score": 0.85,
            "credibility": {"score": 0.9},
            "quality_score": 0.8,
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert "summary" in missing

    def test_missing_quality_score(self):
        """Test with missing quality_score."""
        state = {
            "category": "tech",
            "score": 0.85,
            "credibility": {"score": 0.9},
            "summary_info": {"summary": "Test summary"},
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert "quality_score" in missing

    def test_multiple_missing_fields(self):
        """Test with multiple missing fields."""
        state = {
            "category": "tech",
        }

        is_complete, missing = is_enrichment_complete(state)

        assert is_complete is False
        assert len(missing) == 4  # score, credibility_score, summary, quality_score


class TestArticleRepoGet:
    """Tests for ArticleRepo.get method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_by_uuid(self, repo, mock_pool):
        """Test get with UUID input."""
        article_id = uuid.uuid4()
        mock_article = MagicMock(spec=Article)
        mock_article.id = article_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get(article_id)

        assert result is mock_article

    @pytest.mark.asyncio
    async def test_get_by_string_uuid(self, repo, mock_pool):
        """Test get with string UUID input."""
        article_id = uuid.uuid4()
        mock_article = MagicMock(spec=Article)
        mock_article.id = article_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get(str(article_id))

        assert result is mock_article

    @pytest.mark.asyncio
    async def test_get_not_found(self, repo, mock_pool):
        """Test get returns None when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get(uuid.uuid4())

        assert result is None


class TestArticleRepoUpsert:
    """Tests for ArticleRepo.upsert method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_upsert_new_article(self, repo, mock_pool):
        """Test upsert creates new article."""
        mock_raw = MagicMock()
        mock_raw.url = "https://example.com/new"
        mock_raw.source_host = "example.com"
        mock_raw.title = "New Article"
        mock_raw.body = "Article body"

        state = {"raw": mock_raw, "is_news": True}

        # First query returns None (no existing)
        mock_select_result = MagicMock()
        mock_select_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_select_result
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.add = MagicMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.upsert(state)

        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_existing_article(self, repo, mock_pool):
        """Test upsert updates existing article."""
        article_id = uuid.uuid4()
        mock_existing = MagicMock(spec=Article)
        mock_existing.id = article_id
        mock_existing.source_url = "https://example.com/existing"

        mock_raw = MagicMock()
        mock_raw.url = "https://example.com/existing"

        state = {"raw": mock_raw, "category": "tech"}

        mock_select_result = MagicMock()
        mock_select_result.scalar_one_or_none.return_value = mock_existing

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_select_result
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.upsert(state)

        assert result == article_id

    @pytest.mark.asyncio
    async def test_upsert_with_error(self, repo, mock_pool):
        """Test upsert handles error with rollback."""
        mock_raw = MagicMock()
        mock_raw.url = "https://example.com/test"

        state = {"raw": mock_raw}

        mock_session = AsyncMock()
        mock_session.execute.side_effect = SQLAlchemyError("DB error")
        mock_session.rollback = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(SQLAlchemyError):
            await repo.upsert(state)

        mock_session.rollback.assert_called_once()


class TestArticleRepoUpdateCredibility:
    """Tests for ArticleRepo.update_credibility method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_update_credibility_by_uuid(self, repo, mock_pool):
        """Test update_credibility with UUID."""
        article_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await repo.update_credibility(
            article_id=article_id,
            credibility_score=0.85,
            cross_verification=0.75,
            verified_by_sources=3,
        )

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_credibility_by_string(self, repo, mock_pool):
        """Test update_credibility with string ID."""
        article_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await repo.update_credibility(
            article_id=str(article_id),
            credibility_score=0.85,
            cross_verification=0.75,
            verified_by_sources=3,
        )

        mock_session.execute.assert_called_once()


class TestArticleRepoGetPendingNeo4j:
    """Tests for ArticleRepo.get_pending_neo4j method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_pending_neo4j(self, repo, mock_pool):
        """Test get_pending_neo4j returns articles with PG_DONE status."""
        mock_article = MagicMock(spec=Article)
        mock_article.persist_status = PersistStatus.PG_DONE

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_article]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get_pending_neo4j(limit=10)

        assert len(result) == 1


class TestArticleRepoGetPending:
    """Tests for ArticleRepo.get_pending method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_pending(self, repo, mock_pool):
        """Test get_pending returns PENDING articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.persist_status = PersistStatus.PENDING

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_article]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get_pending(limit=10)

        assert len(result) == 1


class TestArticleRepoGetAllArticleIds:
    """Tests for ArticleRepo.get_all_article_ids method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_all_article_ids(self, repo, mock_pool):
        """Test get_all_article_ids returns set of IDs."""
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([(id1,), (id2,)])

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get_all_article_ids()

        assert str(id1) in result
        assert str(id2) in result


class TestArticleRepoUpdateEnrichmentIfNull:
    """Tests for ArticleRepo.update_enrichment_if_null method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_update_enrichment_if_null_updates_null_fields(self, repo, mock_pool):
        """Test updates fields that are NULL."""
        article_id = uuid.uuid4()
        mock_article = MagicMock(spec=Article)
        mock_article.category = None
        mock_article.score = None
        mock_article.credibility_score = None
        mock_article.summary = None
        mock_article.quality_score = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.update_enrichment_if_null(
            article_id,
            category="tech",
            score=0.85,
            credibility_score=0.9,
            summary="Summary",
            quality_score=0.8,
        )

        assert result is True
        assert mock_article.category == "tech"
        assert mock_article.score == 0.85

    @pytest.mark.asyncio
    async def test_update_enrichment_if_null_skips_non_null(self, repo, mock_pool):
        """Test skips fields that are not NULL."""
        article_id = uuid.uuid4()
        mock_article = MagicMock(spec=Article)
        mock_article.category = "existing_category"
        mock_article.score = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_article

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.update_enrichment_if_null(
            article_id,
            category="new_category",  # Should not update
            score=0.85,
        )

        assert result is True
        assert mock_article.category == "existing_category"  # Not changed
        assert mock_article.score == 0.85

    @pytest.mark.asyncio
    async def test_update_enrichment_if_null_article_not_found(self, repo, mock_pool):
        """Test returns False when article not found."""
        article_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.update_enrichment_if_null(
            article_id,
            category="tech",
        )

        assert result is False


class TestArticleRepoGetFailedArticles:
    """Tests for ArticleRepo.get_failed_articles method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_failed_articles(self, repo, mock_pool):
        """Test get_failed_articles returns failed articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.persist_status = PersistStatus.FAILED
        mock_article.retry_count = 1

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_article]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get_failed_articles(max_retries=3)

        assert len(result) == 1


class TestArticleRepoUpdateProcessingStage:
    """Tests for ArticleRepo.update_processing_stage method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_update_processing_stage(self, repo, mock_pool):
        """Test update_processing_stage updates stage."""
        article_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await repo.update_processing_stage(article_id, "entity_extraction")

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestArticleRepoMarkFailed:
    """Tests for ArticleRepo.mark_failed method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_mark_failed(self, repo, mock_pool):
        """Test mark_failed sets FAILED status."""
        article_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await repo.mark_failed(article_id, "Processing error")

        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_failed_no_increment(self, repo, mock_pool):
        """Test mark_failed without retry increment."""
        article_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 5

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await repo.mark_failed(article_id, "Error", increment_retry=False)

        mock_session.commit.assert_called_once()


class TestArticleRepoMarkProcessing:
    """Tests for ArticleRepo.mark_processing method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_mark_processing(self, repo, mock_pool):
        """Test mark_processing sets PROCESSING status."""
        article_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        await repo.mark_processing(article_id, "start")

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestArticleRepoDetectMergeCycle:
    """Tests for ArticleRepo.detect_merge_cycle method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_detect_merge_cycle_self_merge(self, repo):
        """Test detects cycle when merging to self."""
        article_id = uuid.uuid4()

        result = await repo.detect_merge_cycle(article_id, article_id)

        assert result == [article_id, article_id]

    @pytest.mark.asyncio
    async def test_detect_merge_cycle_no_cycle(self, repo, mock_pool):
        """Test returns None when no cycle detected."""
        article_id = uuid.uuid4()
        target_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.detect_merge_cycle(article_id, target_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_detect_merge_cycle_with_chain(self, repo, mock_pool):
        """Test detects no cycle when there's a valid chain."""
        article_id = uuid.uuid4()
        target_id = uuid.uuid4()
        final_target = uuid.uuid4()

        # Simulate: target -> final_target -> None (no cycle)
        mock_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=final_target)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]

        mock_session = AsyncMock()
        mock_session.execute.side_effect = mock_results

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.detect_merge_cycle(article_id, target_id)

        # No cycle should be detected
        assert result is None


class TestArticleRepoResolveFinalMergeTarget:
    """Tests for ArticleRepo.resolve_final_merge_target method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_resolve_final_merge_target_no_merge(self, repo, mock_pool):
        """Test returns same ID when no merge."""
        article_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.resolve_final_merge_target(article_id)

        assert result == article_id

    @pytest.mark.asyncio
    async def test_resolve_final_merge_target_with_merge(self, repo, mock_pool):
        """Test follows merge chain to final target."""
        article_id = uuid.uuid4()
        intermediate_id = uuid.uuid4()
        final_id = uuid.uuid4()

        mock_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=intermediate_id)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=final_id)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]

        mock_session = AsyncMock()
        mock_session.execute.side_effect = mock_results

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.resolve_final_merge_target(article_id)

        assert result == final_id


class TestArticleRepoGetIncompleteArticles:
    """Tests for ArticleRepo.get_incomplete_articles method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_incomplete_articles(self, repo, mock_pool):
        """Test get_incomplete_articles returns incomplete articles."""
        mock_article = MagicMock(spec=Article)
        mock_article.persist_status = PersistStatus.NEO4J_DONE
        mock_article.category = None  # Missing

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_article]

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get_incomplete_articles(limit=10)

        assert len(result) == 1


class TestArticleRepoGetTaskProgressStats:
    """Tests for ArticleRepo.get_task_progress_stats method."""

    @pytest.fixture
    def mock_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create ArticleRepo instance."""
        return ArticleRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_get_task_progress_stats(self, repo, mock_pool):
        """Test get_task_progress_stats returns stats."""
        task_id = uuid.uuid4()

        mock_row = MagicMock()
        mock_row.total_processed = 10
        mock_row.processing_count = 2
        mock_row.completed_count = 5
        mock_row.failed_count = 1
        mock_row.pending_count = 2

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.get_task_progress_stats(task_id)

        assert result["total_processed"] == 10
        assert result["processing_count"] == 2
        assert result["completed_count"] == 5
        assert result["failed_count"] == 1
        assert result["pending_count"] == 2
