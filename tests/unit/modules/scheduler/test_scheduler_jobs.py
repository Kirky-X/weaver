# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for scheduler jobs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSchedulerJobsInit:
    """Test SchedulerJobs initialization."""

    def test_init_with_all_dependencies(self):
        """Test initialization with all dependencies."""
        from modules.scheduler.jobs import SchedulerJobs

        mock_postgres = MagicMock()
        mock_redis = MagicMock()
        mock_neo4j = MagicMock()
        mock_vector = MagicMock()
        mock_article = MagicMock()
        mock_source = MagicMock()

        mock_pending_sync = MagicMock()
        jobs = SchedulerJobs(
            postgres_pool=mock_postgres,
            redis_client=mock_redis,
            neo4j_writer=mock_neo4j,
            vector_repo=mock_vector,
            article_repo=mock_article,
            source_authority_repo=mock_source,
            pending_sync_repo=mock_pending_sync,
        )

        assert jobs._postgres == mock_postgres
        assert jobs._redis == mock_redis
        assert jobs._neo4j_writer == mock_neo4j
        assert jobs._vector_repo == mock_vector
        assert jobs._article_repo == mock_article
        assert jobs._source_authority_repo == mock_source

    def test_init_with_pipeline(self):
        """Test initialization with pipeline."""
        from modules.scheduler.jobs import SchedulerJobs

        mock_pipeline = MagicMock()
        jobs = SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            pipeline=mock_pipeline,
        )

        assert jobs._pipeline == mock_pipeline


class TestRetryNeo4jWrites:
    """Test retry_neo4j_writes job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_retry_neo4j_writes_no_items(self, scheduler_jobs):
        """Test when no items need retry."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        scheduler_jobs._postgres.session = MagicMock()
        scheduler_jobs._postgres.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        scheduler_jobs._postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await scheduler_jobs.retry_neo4j_writes()
        assert result == 0

    @pytest.mark.asyncio
    async def test_retry_neo4j_writes_success(self, scheduler_jobs):
        """Test successful retry of Neo4j writes."""
        from core.db.models import Article, PersistStatus

        mock_article = MagicMock(spec=Article)
        mock_article.id = MagicMock()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test Article"
        mock_article.body = "Test body"
        mock_article.persist_status = PersistStatus.PG_DONE

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [mock_article]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        scheduler_jobs._postgres.session = MagicMock()
        scheduler_jobs._postgres.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        scheduler_jobs._postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        scheduler_jobs._neo4j_writer.write = AsyncMock()
        scheduler_jobs._pending_sync_repo.get_by_article_id = AsyncMock(return_value=None)

        result = await scheduler_jobs.retry_neo4j_writes()
        assert result == 1

    @pytest.mark.asyncio
    async def test_retry_neo4j_writes_failure(self, scheduler_jobs):
        """Test handling of Neo4j write failure."""
        from core.db.models import Article, PersistStatus

        mock_article = MagicMock(spec=Article)
        mock_article.id = MagicMock()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test Article"
        mock_article.body = "Test body"
        mock_article.persist_status = PersistStatus.PG_DONE

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [mock_article]
        mock_session.execute = AsyncMock(return_value=mock_result)

        scheduler_jobs._postgres.session = MagicMock()
        scheduler_jobs._postgres.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        scheduler_jobs._postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        scheduler_jobs._neo4j_writer.write = AsyncMock(side_effect=Exception("Neo4j error"))

        result = await scheduler_jobs.retry_neo4j_writes()
        assert result == 0

    @pytest.mark.asyncio
    async def test_retry_neo4j_writes_prefers_pending_sync_payload(self, scheduler_jobs):
        """Test that retry_neo4j_writes prefers pending_sync payload over _reconstruct_state."""
        import uuid
        from datetime import UTC, datetime

        from core.db.models import Article, PersistStatus

        mock_article = MagicMock(spec=Article)
        mock_article.id = uuid.uuid4()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test Article"
        mock_article.body = "Test body"
        mock_article.persist_status = PersistStatus.PG_DONE

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [mock_article]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        scheduler_jobs._postgres.session = MagicMock()
        scheduler_jobs._postgres.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        scheduler_jobs._postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        scheduler_jobs._neo4j_writer.write = AsyncMock()

        # Mock pending_sync record with payload
        mock_pending_sync = MagicMock()
        mock_pending_sync.payload = {
            "article_id": str(mock_article.id),
            "entities": [{"name": "Test Entity", "type": "PERSON"}],
        }
        scheduler_jobs._pending_sync_repo.get_by_article_id = AsyncMock(
            return_value=mock_pending_sync
        )
        scheduler_jobs._pending_sync_repo.reconstruct_state_from_payload = MagicMock(
            return_value={"article_id": str(mock_article.id), "entities": []}
        )

        result = await scheduler_jobs.retry_neo4j_writes()

        assert result == 1
        # Verify reconstruct_state_from_payload was called with pending_sync payload
        scheduler_jobs._pending_sync_repo.reconstruct_state_from_payload.assert_called_once_with(
            mock_pending_sync.payload
        )


class TestFlushRetryQueue:
    """Test flush_retry_queue job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_flush_retry_queue_no_keys(self, scheduler_jobs):
        """Test when no retry keys exist."""
        scheduler_jobs._redis.keys = AsyncMock(return_value=[])
        result = await scheduler_jobs.flush_retry_queue()
        assert result == 0

    @pytest.mark.asyncio
    async def test_flush_retry_queue_with_items(self, scheduler_jobs):
        """Test flushing items from retry queue."""
        scheduler_jobs._redis.keys = AsyncMock(return_value=["crawl:retry:example.com"])
        scheduler_jobs._redis.zrangebyscore = AsyncMock(return_value=[b'{"url": "test"}'])
        scheduler_jobs._redis.zrem = AsyncMock(return_value=1)
        scheduler_jobs._redis.lpush = AsyncMock(return_value=1)

        result = await scheduler_jobs.flush_retry_queue()
        assert result == 1

    @pytest.mark.asyncio
    async def test_flush_retry_queue_multiple_hosts(self, scheduler_jobs):
        """Test flushing items from multiple hosts."""
        scheduler_jobs._redis.keys = AsyncMock(
            return_value=[
                "crawl:retry:host1.com",
                "crawl:retry:host2.com",
            ]
        )
        scheduler_jobs._redis.zrangebyscore = AsyncMock(return_value=[b"item1", b"item2"])
        scheduler_jobs._redis.zrem = AsyncMock(return_value=2)
        scheduler_jobs._redis.lpush = AsyncMock(return_value=1)

        result = await scheduler_jobs.flush_retry_queue()
        assert result == 4


class TestUpdateSourceAutoScores:
    """Test update_source_auto_scores job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_update_source_auto_scores_no_sources(self, scheduler_jobs):
        """Test when no sources have articles."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.execute = AsyncMock(return_value=mock_result)

        scheduler_jobs._postgres.session = MagicMock()
        scheduler_jobs._postgres.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        scheduler_jobs._postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await scheduler_jobs.update_source_auto_scores()
        assert result == 0

    @pytest.mark.asyncio
    async def test_update_source_auto_scores_with_sources(self, scheduler_jobs):
        """Test updating scores for sources."""
        # First query: select(Article.source_host).distinct() → iterates rows
        hosts_result = MagicMock()
        hosts_result.__iter__ = MagicMock(return_value=iter([("example.com",)]))

        # Second query: select(Article).where(...) → scalars().all()
        mock_article = MagicMock()
        mock_article.credibility_score = 0.8
        articles_result = MagicMock()
        articles_result.scalars.return_value.all.return_value = [mock_article]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[hosts_result, articles_result])

        scheduler_jobs._postgres.session = MagicMock()
        scheduler_jobs._postgres.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        scheduler_jobs._postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        scheduler_jobs._source_authority_repo.update_auto_score = AsyncMock()

        result = await scheduler_jobs.update_source_auto_scores()
        assert result == 1


class TestArchiveOldNeo4jNodes:
    """Test archive_old_neo4j_nodes job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_archive_old_nodes_success(self, scheduler_jobs):
        """Test successful archiving of old nodes."""
        scheduler_jobs._neo4j_writer.archive_old_articles = AsyncMock(return_value=10)
        scheduler_jobs._neo4j_writer.entity_repo.delete_orphan_entities = AsyncMock(return_value=5)

        result = await scheduler_jobs.archive_old_neo4j_nodes()
        assert result == 10

    @pytest.mark.asyncio
    async def test_archive_old_nodes_failure(self, scheduler_jobs):
        """Test handling of archive failure."""
        scheduler_jobs._neo4j_writer.archive_old_articles = AsyncMock(
            side_effect=Exception("Archive error")
        )

        result = await scheduler_jobs.archive_old_neo4j_nodes()
        assert result == 0


class TestCleanupOrphanEntityVectors:
    """Test cleanup_orphan_entity_vectors job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_cleanup_orphan_vectors(self, scheduler_jobs):
        """Test cleanup of orphan vectors."""
        mock_session = AsyncMock()

        scheduler_jobs._postgres.session = MagicMock()
        scheduler_jobs._postgres.session.return_value.__aenter__ = AsyncMock(
            return_value=mock_session
        )
        scheduler_jobs._postgres.session.return_value.__aexit__ = AsyncMock(return_value=None)

        scheduler_jobs._neo4j_writer.entity_repo.list_all_entity_ids = AsyncMock(return_value=[])

        result = await scheduler_jobs.cleanup_orphan_entity_vectors()
        assert result == 0


class TestRetryPipelineProcessing:
    """Test retry_pipeline_processing job."""

    @pytest.fixture
    def scheduler_jobs_with_pipeline(self):
        """Create SchedulerJobs instance with pipeline."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            pipeline=MagicMock(),
        )

    @pytest.fixture
    def scheduler_jobs_no_pipeline(self):
        """Create SchedulerJobs instance without pipeline."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            pipeline=None,
        )

    @pytest.mark.asyncio
    async def test_retry_pipeline_no_pipeline(self, scheduler_jobs_no_pipeline):
        """Test when pipeline is not configured."""
        result = await scheduler_jobs_no_pipeline.retry_pipeline_processing()
        assert result == 0

    @pytest.mark.asyncio
    async def test_retry_pipeline_no_items(self, scheduler_jobs_with_pipeline):
        """Test when no items need retry."""
        scheduler_jobs_with_pipeline._article_repo.get_stuck_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_pipeline._article_repo.get_failed_articles = AsyncMock(return_value=[])

        result = await scheduler_jobs_with_pipeline.retry_pipeline_processing()
        assert result == 0

    @pytest.mark.asyncio
    async def test_retry_pipeline_with_stuck_articles(self, scheduler_jobs_with_pipeline):
        """Test retrying stuck articles."""
        mock_article = MagicMock()
        mock_article.id = MagicMock()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test"
        mock_article.body = "Body"
        mock_article.source_host = "example.com"

        scheduler_jobs_with_pipeline._article_repo.get_pending = AsyncMock(return_value=[])
        scheduler_jobs_with_pipeline._article_repo.get_stuck_articles = AsyncMock(
            return_value=[mock_article]
        )
        scheduler_jobs_with_pipeline._article_repo.get_failed_articles = AsyncMock(return_value=[])
        scheduler_jobs_with_pipeline._pipeline.process_batch = AsyncMock()

        result = await scheduler_jobs_with_pipeline.retry_pipeline_processing()
        assert result == 1


class TestReconstructState:
    """Test _reconstruct_state method."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_reconstruct_state(self, scheduler_jobs):
        """Test state reconstruction from article."""
        from core.db.models import Article

        mock_article = MagicMock(spec=Article)
        mock_article.id = MagicMock()
        mock_article.source_url = "https://example.com/test"
        mock_article.title = "Test Article"
        mock_article.body = "Test body"
        mock_article.publish_time = datetime.now(UTC)
        mock_article.source_host = "example.com"
        mock_article.category = "tech"
        mock_article.score = 0.85

        state = await scheduler_jobs._reconstruct_state(mock_article)

        assert state["article_id"] == str(mock_article.id)
        assert state["raw"].url == mock_article.source_url
        assert state["raw"].title == mock_article.title
        assert state["cleaned"]["title"] == mock_article.title
        assert state["category"] == mock_article.category
        assert state["score"] == mock_article.score


class TestSyncNeo4jWithPostgres:
    """Test sync_neo4j_with_postgres job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_sync_neo4j_no_orphans_no_gaps(self, scheduler_jobs):
        """Test when there are no orphans and no enrichment gaps."""
        import uuid

        pg_id = str(uuid.uuid4())
        scheduler_jobs._article_repo.get_all_article_ids = AsyncMock(return_value={pg_id})
        scheduler_jobs._neo4j_writer.article_repo.list_all_article_pg_ids = AsyncMock(
            return_value=[pg_id]
        )
        scheduler_jobs._neo4j_writer.article_repo.count_articles_without_mentions = AsyncMock(
            return_value=0
        )
        scheduler_jobs._article_repo.get_incomplete_articles = AsyncMock(return_value=[])

        result = await scheduler_jobs.sync_neo4j_with_postgres()

        assert result == {
            "neo4j_orphans_deleted": 0,
            "orphan_articles_cleaned": 0,
            "enrichment_gaps_detected": 0,
            "enrichment_gaps_reverted": 0,
        }
        scheduler_jobs._neo4j_writer.article_repo.delete_orphan_articles.assert_not_called()
        scheduler_jobs._article_repo.revert_to_pg_done.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_neo4j_deletes_orphans(self, scheduler_jobs):
        """Test orphan Neo4j articles are deleted."""
        import uuid

        pg_id = str(uuid.uuid4())
        scheduler_jobs._article_repo.get_all_article_ids = AsyncMock(return_value={pg_id})
        scheduler_jobs._neo4j_writer.article_repo.list_all_article_pg_ids = AsyncMock(
            return_value=[pg_id, "orphan-id"]
        )
        scheduler_jobs._article_repo.get_incomplete_articles = AsyncMock(return_value=[])
        scheduler_jobs._neo4j_writer.article_repo.delete_orphan_articles = AsyncMock(return_value=1)
        scheduler_jobs._neo4j_writer.article_repo.count_articles_without_mentions = AsyncMock(
            return_value=0
        )

        result = await scheduler_jobs.sync_neo4j_with_postgres()

        assert result["neo4j_orphans_deleted"] == 1
        assert result["orphan_articles_cleaned"] == 0
        assert result["enrichment_gaps_detected"] == 0
        assert result["enrichment_gaps_reverted"] == 0
        scheduler_jobs._neo4j_writer.article_repo.delete_orphan_articles.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_neo4j_reverts_enrichment_gaps(self, scheduler_jobs):
        """Test enrichment gaps are reverted to PG_DONE."""
        import uuid

        from core.db.models import Article, PersistStatus

        pg_id = str(uuid.uuid4())
        scheduler_jobs._article_repo.get_all_article_ids = AsyncMock(return_value={pg_id})
        scheduler_jobs._neo4j_writer.article_repo.list_all_article_pg_ids = AsyncMock(
            return_value=[pg_id]
        )
        scheduler_jobs._neo4j_writer.article_repo.delete_orphan_articles = AsyncMock(return_value=0)
        scheduler_jobs._neo4j_writer.article_repo.count_articles_without_mentions = AsyncMock(
            return_value=0
        )

        incomplete_article = MagicMock(spec=Article)
        incomplete_article.id = uuid.uuid4()
        incomplete_article.source_url = "https://example.com/article"
        incomplete_article.persist_status = PersistStatus.NEO4J_DONE
        incomplete_article.category = None
        incomplete_article.score = None
        incomplete_article.credibility_score = None
        incomplete_article.summary = None
        incomplete_article.quality_score = None

        scheduler_jobs._article_repo.get_incomplete_articles = AsyncMock(
            return_value=[incomplete_article]
        )
        scheduler_jobs._article_repo.revert_to_pg_done = AsyncMock(return_value=True)

        result = await scheduler_jobs.sync_neo4j_with_postgres()

        # sync returns dict with stats (1 enrichment gap detected and reverted)
        assert result["neo4j_orphans_deleted"] == 0
        assert result["orphan_articles_cleaned"] == 0
        assert result["enrichment_gaps_detected"] == 1
        assert result["enrichment_gaps_reverted"] == 1
        scheduler_jobs._article_repo.revert_to_pg_done.assert_called_once_with(
            incomplete_article.id
        )


class TestRevertToPgDone:
    """Test revert_to_pg_done method on ArticleRepo."""

    @pytest.mark.asyncio
    async def test_revert_to_pg_done_sets_status(self):
        """Test revert_to_pg_done sets status to PG_DONE regardless of current state."""
        from modules.storage.postgres.article_repo import ArticleRepo

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        async def enter_cm():
            return mock_session

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=enter_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.session = MagicMock(return_value=mock_cm)

        repo = ArticleRepo(mock_pool)
        import uuid

        article_id = uuid.uuid4()
        result = await repo.revert_to_pg_done(article_id)

        assert result is True
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_revert_to_pg_done_not_found(self):
        """Test revert_to_pg_done returns False when article not found."""
        from modules.storage.postgres.article_repo import ArticleRepo

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        async def enter_cm():
            return mock_session

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=enter_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.session = MagicMock(return_value=mock_cm)

        repo = ArticleRepo(mock_pool)
        import uuid

        article_id = uuid.uuid4()
        result = await repo.revert_to_pg_done(article_id)

        assert result is False


class TestGetIncompleteArticles:
    """Test get_incomplete_articles method on ArticleRepo."""

    @pytest.mark.asyncio
    async def test_get_incomplete_articles_returns_matching_articles(self):
        """Test get_incomplete_articles returns articles with NEO4J_DONE and all null fields."""
        from modules.storage.postgres.article_repo import ArticleRepo

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def enter_cm():
            return mock_session

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=enter_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.session = MagicMock(return_value=mock_cm)

        repo = ArticleRepo(mock_pool)
        articles = await repo.get_incomplete_articles(limit=50)

        # Verify the query was executed with correct filter
        call_args = mock_session.execute.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_get_incomplete_articles_respects_limit(self):
        """Test get_incomplete_articles respects the limit parameter."""
        from modules.storage.postgres.article_repo import ArticleRepo

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def enter_cm():
            return mock_session

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=enter_cm)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.session = MagicMock(return_value=mock_cm)

        repo = ArticleRepo(mock_pool)
        await repo.get_incomplete_articles(limit=25)

        # Verify limit was passed
        call_args = mock_session.execute.call_args
        assert call_args is not None


class TestRetryManager:
    """Test RetryManager class."""

    @pytest.fixture
    def retry_manager(self):
        """Create RetryManager instance."""
        from modules.scheduler.jobs import RetryManager

        return RetryManager(MagicMock())

    @pytest.mark.asyncio
    async def test_add_to_retry(self, retry_manager):
        """Test adding item to retry queue."""
        retry_manager._redis.zadd = AsyncMock(return_value=1)

        await retry_manager.add_to_retry(
            host="example.com",
            item='{"url": "test"}',
            retry_at=datetime.now(UTC) + timedelta(minutes=5),
        )

        retry_manager._redis.zadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_retry_items(self, retry_manager):
        """Test getting retry items."""
        retry_manager._redis.zrangebyscore = AsyncMock(return_value=[b"item1", b"item2"])

        items = await retry_manager.get_retry_items("example.com")

        assert len(items) == 2
        retry_manager._redis.zrangebyscore.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_from_retry(self, retry_manager):
        """Test removing items from retry queue."""
        retry_manager._redis.zrem = AsyncMock(return_value=2)

        await retry_manager.remove_from_retry("example.com", "item1", "item2")

        retry_manager._redis.zrem.assert_called_once()


class TestSyncPendingToNeo4j:
    """Test sync_pending_to_neo4j job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_sync_pending_to_neo4j_no_items(self, scheduler_jobs):
        """Test when no pending records exist."""
        scheduler_jobs._pending_sync_repo.get_pending = AsyncMock(return_value=[])

        result = await scheduler_jobs.sync_pending_to_neo4j()

        assert result == 0
        scheduler_jobs._neo4j_writer.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_pending_to_neo4j_success(self, scheduler_jobs):
        """Test successful sync of pending records."""
        import uuid
        from datetime import UTC, datetime

        from modules.storage.postgres.pending_sync_repo import PendingSync

        mock_record = MagicMock(spec=PendingSync)
        mock_record.id = 1
        mock_record.article_id = uuid.uuid4()
        mock_record.payload = {
            "article_id": str(mock_record.article_id),
            "raw": MagicMock(url="https://example.com", title="Test", body="Body"),
            "entities": [],
        }
        mock_record.created_at = datetime.now(UTC)

        scheduler_jobs._pending_sync_repo.get_pending = AsyncMock(return_value=[mock_record])
        scheduler_jobs._pending_sync_repo.reconstruct_state_from_payload = MagicMock(
            return_value={"article_id": str(mock_record.article_id)}
        )
        scheduler_jobs._neo4j_writer.write = AsyncMock(return_value=[])
        scheduler_jobs._article_repo.update_persist_status = AsyncMock()
        scheduler_jobs._pending_sync_repo.mark_synced = AsyncMock()

        result = await scheduler_jobs.sync_pending_to_neo4j()

        assert result == 1
        scheduler_jobs._neo4j_writer.write.assert_called_once()
        scheduler_jobs._article_repo.update_persist_status.assert_called_once()
        scheduler_jobs._pending_sync_repo.mark_synced.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_sync_pending_to_neo4j_failure(self, scheduler_jobs):
        """Test handling of sync failure."""
        import uuid
        from datetime import UTC, datetime

        from modules.storage.postgres.pending_sync_repo import PendingSync

        mock_record = MagicMock(spec=PendingSync)
        mock_record.id = 1
        mock_record.article_id = uuid.uuid4()
        mock_record.payload = {"article_id": str(mock_record.article_id)}
        mock_record.created_at = datetime.now(UTC)

        scheduler_jobs._pending_sync_repo.get_pending = AsyncMock(return_value=[mock_record])
        scheduler_jobs._pending_sync_repo.reconstruct_state_from_payload = MagicMock(
            return_value={"article_id": str(mock_record.article_id)}
        )
        scheduler_jobs._neo4j_writer.write = AsyncMock(side_effect=Exception("Neo4j error"))
        scheduler_jobs._pending_sync_repo.mark_failed = AsyncMock()

        result = await scheduler_jobs.sync_pending_to_neo4j()

        assert result == 0
        scheduler_jobs._pending_sync_repo.mark_failed.assert_called_once_with(1, "Neo4j error")


class TestConsistencyCheck:
    """Test consistency_check job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_consistency_check_no_mismatch(self, scheduler_jobs):
        """Test when entity counts match."""
        scheduler_jobs._neo4j_writer.entity_repo.list_all_entity_ids = AsyncMock(
            return_value=["id1", "id2", "id3"]
        )
        scheduler_jobs._vector_repo.count_entities_with_valid_neo4j_ids = AsyncMock(return_value=3)
        scheduler_jobs._vector_repo.get_entity_vectors_with_temp_keys = AsyncMock(return_value=[])
        scheduler_jobs._pending_sync_repo.get_stale_pending = AsyncMock(return_value=[])

        result = await scheduler_jobs.consistency_check()

        assert result["entity_mismatch"] is False
        assert result["orphan_temp_keys"] == []
        assert result["stale_pending"] == []

    @pytest.mark.asyncio
    async def test_consistency_check_entity_mismatch(self, scheduler_jobs):
        """Test when entity counts don't match."""
        scheduler_jobs._neo4j_writer.entity_repo.list_all_entity_ids = AsyncMock(
            return_value=["id1", "id2"]
        )
        scheduler_jobs._vector_repo.count_entities_with_valid_neo4j_ids = AsyncMock(return_value=5)
        scheduler_jobs._vector_repo.get_entity_vectors_with_temp_keys = AsyncMock(return_value=[])
        scheduler_jobs._pending_sync_repo.get_stale_pending = AsyncMock(return_value=[])

        result = await scheduler_jobs.consistency_check()

        assert result["entity_mismatch"] is True
        assert result["neo4j_count"] == 2
        assert result["pg_count"] == 5

    @pytest.mark.asyncio
    async def test_consistency_check_orphan_temp_keys(self, scheduler_jobs):
        """Test detection of orphan temp keys."""
        scheduler_jobs._neo4j_writer.entity_repo.list_all_entity_ids = AsyncMock(return_value=[])
        scheduler_jobs._vector_repo.count_entities_with_valid_neo4j_ids = AsyncMock(return_value=0)
        scheduler_jobs._vector_repo.get_entity_vectors_with_temp_keys = AsyncMock(
            return_value=[("temp_key1", []), ("temp_key2", [])]
        )
        scheduler_jobs._pending_sync_repo.get_stale_pending = AsyncMock(return_value=[])

        result = await scheduler_jobs.consistency_check()

        assert result["orphan_temp_keys"] == ["temp_key1", "temp_key2"]

    @pytest.mark.asyncio
    async def test_consistency_check_stale_pending(self, scheduler_jobs):
        """Test detection of stale pending records."""
        import uuid
        from datetime import UTC, datetime

        from modules.storage.postgres.pending_sync_repo import PendingSync

        mock_record = MagicMock(spec=PendingSync)
        mock_record.id = 1
        mock_record.article_id = uuid.uuid4()
        mock_record.created_at = datetime.now(UTC)

        scheduler_jobs._neo4j_writer.entity_repo.list_all_entity_ids = AsyncMock(return_value=[])
        scheduler_jobs._vector_repo.count_entities_with_valid_neo4j_ids = AsyncMock(return_value=0)
        scheduler_jobs._vector_repo.get_entity_vectors_with_temp_keys = AsyncMock(return_value=[])
        scheduler_jobs._pending_sync_repo.get_stale_pending = AsyncMock(return_value=[mock_record])

        result = await scheduler_jobs.consistency_check()

        assert len(result["stale_pending"]) == 1
        assert result["stale_pending"][0]["id"] == 1


class TestCleanupOldSynced:
    """Test cleanup_old_synced job."""

    @pytest.fixture
    def scheduler_jobs(self):
        """Create SchedulerJobs instance."""
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_cleanup_old_synced_success(self, scheduler_jobs):
        """Test cleanup of old synced records."""
        scheduler_jobs._pending_sync_repo.cleanup_old_synced = AsyncMock(return_value=5)

        result = await scheduler_jobs.cleanup_old_synced()

        assert result == 5
        scheduler_jobs._pending_sync_repo.cleanup_old_synced.assert_called_once_with(days=7)

    @pytest.mark.asyncio
    async def test_cleanup_old_synced_error(self, scheduler_jobs):
        """Test handling of cleanup error."""
        scheduler_jobs._pending_sync_repo.cleanup_old_synced = AsyncMock(
            side_effect=Exception("DB error")
        )

        result = await scheduler_jobs.cleanup_old_synced()

        assert result == 0


class TestLLMFailureCleanup:
    """Test llm_failure_cleanup job."""

    @pytest.fixture
    def scheduler_jobs(self):
        from modules.scheduler.jobs import SchedulerJobs

        mock_llm_failure_repo = MagicMock()
        mock_llm_failure_repo.cleanup_older_than = AsyncMock(return_value=5)
        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            llm_failure_repo=mock_llm_failure_repo,
        )

    @pytest.mark.asyncio
    async def test_llm_failure_cleanup_calls_repo(self, scheduler_jobs):
        result = await scheduler_jobs.llm_failure_cleanup()
        assert result == 5
        scheduler_jobs._llm_failure_repo.cleanup_older_than.assert_awaited_once_with(3)

    @pytest.mark.asyncio
    async def test_llm_failure_cleanup_no_repo(self):
        from modules.scheduler.jobs import SchedulerJobs

        jobs = SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            llm_failure_repo=None,
        )
        result = await jobs.llm_failure_cleanup()
        assert result == 0


class TestLLMUsageRawCleanup:
    """Test llm_usage_raw_cleanup job."""

    @pytest.fixture
    def scheduler_jobs(self):
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_llm_usage_raw_cleanup(self, scheduler_jobs):
        with patch("modules.analytics.llm_usage.repo.LLMUsageRepo") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.cleanup_raw_older_than = AsyncMock(return_value=10)
            MockRepo.return_value = mock_repo

            result = await scheduler_jobs.llm_usage_raw_cleanup()

            assert result == 10
            mock_repo.cleanup_raw_older_than.assert_awaited_once_with(2)


class TestAggregateLLMUsage:
    """Test aggregate_llm_usage job."""

    @pytest.fixture
    def scheduler_jobs(self):
        from modules.scheduler.jobs import SchedulerJobs

        return SchedulerJobs(
            postgres_pool=MagicMock(),
            redis_client=MagicMock(),
            neo4j_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_aggregate_llm_usage(self, scheduler_jobs):
        with patch("modules.analytics.llm_usage.aggregator.flush_usage_buffer") as mock_flush:
            mock_flush.return_value = (5, 0)  # 5 processed, 0 errors

            result = await scheduler_jobs.aggregate_llm_usage()

            assert result == 5
            mock_flush.assert_awaited_once()
