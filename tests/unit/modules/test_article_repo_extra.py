# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ArticleRepo additional methods to improve coverage."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from core.db import Article, PersistStatus
from core.exceptions import InvalidStateTransitionError
from modules.storage.postgres.article_repo import (
    ArticleRepo,
)


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
        """Test upsert creates new article via ON CONFLICT DO UPDATE."""
        mock_raw = MagicMock()
        mock_raw.url = "https://example.com/new"
        mock_raw.source_host = "example.com"
        mock_raw.title = "New Article"
        mock_raw.body = "Article body"

        state = {"raw": mock_raw, "is_news": True}

        # _upsert_single executes multiple statements:
        # 1. select existing ArticleCore (no existing article → None)
        # 2. pg_insert(ArticleCore) ON CONFLICT
        # 3. select(ArticleCore.id) to get the ID
        # 4. pg_insert(ArticleBody) ON CONFLICT
        # 5. pg_insert(ArticleAnalysis) ON CONFLICT
        article_id = uuid.uuid4()

        mock_existing_result = MagicMock()
        mock_existing_result.one_or_none.return_value = None

        mock_core_result = MagicMock()
        mock_core_result.scalar_one.return_value = article_id

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            mock_existing_result,  # select existing ArticleCore
            MagicMock(),  # pg_insert ArticleCore
            mock_core_result,  # select ArticleCore.id
            MagicMock(),  # pg_insert ArticleBody
            MagicMock(),  # pg_insert ArticleAnalysis
        ]
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.upsert(state)

        assert result == article_id
        assert mock_session.execute.call_count == 5

    @pytest.mark.asyncio
    async def test_upsert_existing_article(self, repo, mock_pool):
        """Test upsert updates existing article via ON CONFLICT DO UPDATE."""
        article_id = uuid.uuid4()

        mock_raw = MagicMock()
        mock_raw.url = "https://example.com/existing"
        mock_raw.source_host = "example.com"
        mock_raw.title = "Existing Article"
        mock_raw.body = "Article body"

        state = {"raw": mock_raw, "category": "tech", "is_news": True}

        # _upsert_single executes multiple statements:
        # 1. select existing ArticleCore (found, but same content_hash → no version snapshot)
        # 2. pg_insert(ArticleCore) ON CONFLICT DO UPDATE
        # 3. select(ArticleCore.id) to get the ID
        # 4. pg_insert(ArticleBody) ON CONFLICT
        # 5. pg_insert(ArticleAnalysis) ON CONFLICT

        # Compute the content_hash that ChangeDetector will produce
        from core.change_detector import ChangeDetector

        content_hash = ChangeDetector.compute_hash(
            {"title": "Existing Article", "body": "Article body"}
        )

        mock_existing_result = MagicMock()
        mock_existing_result.one_or_none.return_value = (
            article_id,
            "Existing Article",
            "tech",
            0.85,
            content_hash,  # Same hash → no version snapshot
        )

        mock_core_result = MagicMock()
        mock_core_result.scalar_one.return_value = article_id

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            mock_existing_result,  # select existing ArticleCore
            MagicMock(),  # pg_insert ArticleCore
            mock_core_result,  # select ArticleCore.id
            MagicMock(),  # pg_insert ArticleBody
            MagicMock(),  # pg_insert ArticleAnalysis
        ]
        mock_session.commit = AsyncMock()

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
        """Test update_credibility with UUID splits across ArticleCore and ArticleAnalysis."""
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

        # update_credibility now executes 2 UPDATE statements:
        # 1. UPDATE ArticleCore SET credibility_score=...
        # 2. UPDATE ArticleAnalysis SET cross_verification=..., verified_by_sources=...
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_credibility_by_string(self, repo, mock_pool):
        """Test update_credibility with string ID splits across ArticleCore and ArticleAnalysis."""
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

        # update_credibility now executes 2 UPDATE statements
        assert mock_session.execute.call_count == 2


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
        """Test get_pending_neo4j returns articles with STORED status."""
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
        """Test updates fields that are NULL across split tables."""
        article_id = uuid.uuid4()

        # update_enrichment_if_null queries each split table separately:
        # 1. SELECT category, score, credibility_score FROM ArticleCore WHERE id=...
        # 2. SELECT summary FROM ArticleBody WHERE article_id=...
        # 3. SELECT quality_score FROM ArticleAnalysis WHERE article_id=...
        # Then executes UPDATE statements for fields that are NULL.

        mock_core_result = MagicMock()
        mock_core_result.one_or_none.return_value = (
            None,
            None,
            None,
        )  # category, score, credibility_score all NULL

        mock_body_result = MagicMock()
        mock_body_result.scalar_one_or_none.return_value = None  # summary is NULL

        mock_analysis_result = MagicMock()
        mock_analysis_result.scalar_one_or_none.return_value = None  # quality_score is NULL

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            mock_core_result,  # SELECT from ArticleCore
            MagicMock(),  # UPDATE ArticleCore
            mock_body_result,  # SELECT from ArticleBody
            MagicMock(),  # UPDATE ArticleBody
            mock_analysis_result,  # SELECT from ArticleAnalysis
            MagicMock(),  # UPDATE ArticleAnalysis
        ]
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

    @pytest.mark.asyncio
    async def test_update_enrichment_if_null_skips_non_null(self, repo, mock_pool):
        """Test skips fields that are not NULL across split tables."""
        article_id = uuid.uuid4()

        # category is "existing_category" (non-NULL), score is NULL
        mock_core_result = MagicMock()
        mock_core_result.one_or_none.return_value = ("existing_category", None, None)

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            mock_core_result,  # SELECT from ArticleCore
            MagicMock(),  # UPDATE ArticleCore (only score + credibility_score, not category)
        ]
        mock_session.commit = AsyncMock()

        mock_pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await repo.update_enrichment_if_null(
            article_id,
            category="new_category",  # Should not update (non-NULL)
            score=0.85,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_update_enrichment_if_null_article_not_found(self, repo, mock_pool):
        """Test returns False when article not found."""
        article_id = uuid.uuid4()

        # ArticleCore query returns None (article not found)
        mock_core_result = MagicMock()
        mock_core_result.one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.side_effect = [
            mock_core_result,  # SELECT from ArticleCore - not found
        ]

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
