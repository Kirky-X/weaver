# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for scheduler jobs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

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

        jobs = SchedulerJobs(
            postgres_pool=mock_postgres,
            redis_client=mock_redis,
            neo4j_writer=mock_neo4j,
            vector_repo=mock_vector,
            article_repo=mock_article,
            source_authority_repo=mock_source,
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
        mock_session = AsyncMock()

        mock_hosts_result = MagicMock()
        mock_hosts_result.__iter__ = MagicMock(return_value=iter([("example.com",)]))

        mock_article = MagicMock()
        mock_article.credibility_score = 0.8
        mock_articles_result = MagicMock()
        mock_articles_result.scalars().all.return_value = [mock_article]

        mock_session.execute = AsyncMock(side_effect=[mock_hosts_result, mock_articles_result])

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
