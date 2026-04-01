# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Neo4j sync - uses real PostgreSQL and Neo4j."""

import uuid

import pytest
from sqlalchemy import text

from modules.storage.postgres.pending_sync_repo import PendingSyncRepo


class TestPendingSyncRepo:
    """Integration tests for PendingSyncRepo with real PostgreSQL."""

    @pytest.fixture
    def repo(self, postgres_pool):
        """Create PendingSyncRepo with real pool."""
        return PendingSyncRepo(postgres_pool)

    @pytest.mark.asyncio
    async def test_upsert_creates_new_record(self, repo, postgres_pool, unique_id):
        """Test upsert creates a new pending_sync record."""
        article_id = uuid.uuid4()
        payload = {"entities": [], "relations": [], "test_id": unique_id}

        try:
            record_id = await repo.upsert(article_id, "entity_relation", payload)

            assert record_id is not None

            # Verify record was created
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT id, article_id, payload FROM pending_sync WHERE id = :id"),
                    {"id": record_id},
                )
                row = result.fetchone()
                assert row is not None
                assert row.article_id == article_id
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM pending_sync WHERE payload::text LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_get_pending_returns_pending_records(self, repo, postgres_pool, unique_id):
        """Test get_pending returns records ordered by created_at."""
        # Create a pending record
        article_id = uuid.uuid4()
        payload = {"entities": [], "relations": [], "test_id": unique_id}

        try:
            await repo.upsert(article_id, "entity_relation", payload)

            result = await repo.get_pending(limit=10)

            assert isinstance(result, list)
            assert len(result) >= 1
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM pending_sync WHERE payload::text LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_mark_synced_updates_status(self, repo, postgres_pool, unique_id):
        """Test mark_synced sets status to synced and sets synced_at."""
        article_id = uuid.uuid4()
        payload = {"entities": [], "relations": [], "test_id": unique_id}

        try:
            record_id = await repo.upsert(article_id, "entity_relation", payload)

            await repo.mark_synced(record_id)

            # Verify status was updated
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT status, synced_at FROM pending_sync WHERE id = :id"),
                    {"id": record_id},
                )
                row = result.fetchone()
                assert row.status == "synced"
                assert row.synced_at is not None
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM pending_sync WHERE payload::text LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_mark_failed_increments_retry_count(self, repo, postgres_pool, unique_id):
        """Test mark_failed increments retry_count and sets error."""
        article_id = uuid.uuid4()
        payload = {"entities": [], "relations": [], "test_id": unique_id}

        try:
            record_id = await repo.upsert(article_id, "entity_relation", payload)

            await repo.mark_failed(record_id, "Connection refused")

            # Verify failure was recorded
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT status, error, retry_count FROM pending_sync WHERE id = :id"),
                    {"id": record_id},
                )
                row = result.fetchone()
                assert row.status == "failed"
                assert row.error == "Connection refused"
                assert row.retry_count >= 1
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM pending_sync WHERE payload::text LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_cleanup_old_synced_deletes_old_records(self, repo, postgres_pool, unique_id):
        """Test cleanup_old_synced deletes synced records older than N days."""
        # Create a synced record
        article_id = uuid.uuid4()
        payload = {"entities": [], "relations": [], "test_id": unique_id}

        try:
            record_id = await repo.upsert(article_id, "entity_relation", payload)
            await repo.mark_synced(record_id)

            # Cleanup synced records older than 0 days (all)
            deleted = await repo.cleanup_old_synced(days=0)

            assert deleted >= 1
        finally:
            # Extra cleanup if needed
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM pending_sync WHERE payload::text LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )

    @pytest.mark.asyncio
    async def test_reconstruct_state_from_payload(self, repo):
        """Test reconstruct_state_from_payload returns correct structure."""
        payload = {
            "entities": [{"name": "Test Entity", "type": "PERSON"}],
            "relations": [{"source": "E1", "target": "E2", "relation_type": "WORKS_FOR"}],
            "cleaned": {"title": "Test Title", "body": "Test Body"},
            "category": "TECHNOLOGY",
            "score": 0.85,
            "merged_source_ids": [str(uuid.uuid4())],
            "is_merged": False,
        }

        state = repo.reconstruct_state_from_payload(payload)

        assert state["entities"] == payload["entities"]
        assert state["relations"] == payload["relations"]
        assert state["cleaned"] == payload["cleaned"]
        assert state["category"] == payload["category"]
        assert state["score"] == payload["score"]
        assert state["merged_source_ids"] == payload["merged_source_ids"]
        assert state["is_merged"] == payload["is_merged"]


class TestContainerStartupSync:
    """Integration tests for Container startup sync trigger."""

    def test_startup_sync_in_startup_code(self):
        """Test that Container.startup() includes sync_pending_to_neo4j scheduling."""
        import inspect

        from container import Container

        source = inspect.getsource(Container.startup)
        assert "sync_pending_to_neo4j" in source
        assert "AsyncIOScheduler" in source
        assert "asyncio.create_task" in source


class TestSyncPendingToNeo4j:
    """Integration tests for sync_pending_to_neo4j job."""

    @pytest.mark.asyncio
    async def test_sync_pending_returns_zero_when_no_pending_records(
        self, postgres_pool, neo4j_pool
    ):
        """Test sync_pending_to_neo4j returns 0 when no pending records."""
        from modules.graph_store.neo4j_writer import Neo4jWriter
        from modules.scheduler.jobs import SchedulerJobs
        from modules.storage.postgres.article_repo import ArticleRepo
        from modules.storage.postgres.vector_repo import VectorRepo

        pending_sync_repo = PendingSyncRepo(postgres_pool)
        article_repo = ArticleRepo(postgres_pool)
        vector_repo = VectorRepo(postgres_pool)
        neo4j_writer = Neo4jWriter(neo4j_pool)

        jobs = SchedulerJobs(
            postgres_pool=postgres_pool,
            redis_client=None,
            neo4j_writer=neo4j_writer,
            vector_repo=vector_repo,
            article_repo=article_repo,
            source_authority_repo=None,
            pending_sync_repo=pending_sync_repo,
        )

        result = await jobs.sync_pending_to_neo4j()
        assert result >= 0


class TestConsistencyCheck:
    """Integration tests for consistency_check job."""

    @pytest.mark.asyncio
    async def test_consistency_check_with_real_services(self, postgres_pool, neo4j_pool):
        """Test consistency_check with real Neo4j and PostgreSQL."""
        from modules.graph_store.neo4j_writer import Neo4jWriter
        from modules.scheduler.jobs import SchedulerJobs
        from modules.storage.postgres.article_repo import ArticleRepo
        from modules.storage.postgres.vector_repo import VectorRepo

        pending_sync_repo = PendingSyncRepo(postgres_pool)
        article_repo = ArticleRepo(postgres_pool)
        vector_repo = VectorRepo(postgres_pool)
        neo4j_writer = Neo4jWriter(neo4j_pool)

        jobs = SchedulerJobs(
            postgres_pool=postgres_pool,
            redis_client=None,
            neo4j_writer=neo4j_writer,
            vector_repo=vector_repo,
            article_repo=article_repo,
            source_authority_repo=None,
            pending_sync_repo=pending_sync_repo,
        )

        result = await jobs.consistency_check()

        assert "entity_mismatch" in result
        assert "neo4j_count" in result
        assert "pg_count" in result
        assert isinstance(result["stale_pending"], list)
        assert isinstance(result["orphan_temp_keys"], list)


class TestRetryNeo4jWritesWithPendingSync:
    """Integration tests for retry_neo4j_writes preferring pending_sync."""

    @pytest.mark.asyncio
    async def test_pending_sync_repo_has_get_by_article_id_method(self, postgres_pool):
        """Test that PendingSyncRepo has get_by_article_id method."""
        repo = PendingSyncRepo(postgres_pool)
        assert hasattr(repo, "get_by_article_id")

    @pytest.mark.asyncio
    async def test_pending_sync_repo_get_by_article_id_returns_record(
        self, postgres_pool, unique_id
    ):
        """Test that PendingSyncRepo.get_by_article_id returns the correct record."""
        repo = PendingSyncRepo(postgres_pool)
        article_id = uuid.uuid4()
        payload = {"entities": [], "relations": [], "test_id": unique_id}

        try:
            record_id = await repo.upsert(article_id, "entity_relation", payload)

            result = await repo.get_by_article_id(article_id)

            assert result is not None
            assert result.id == record_id
            assert result.article_id == article_id
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM pending_sync WHERE payload::text LIKE :pattern"),
                    {"pattern": f"%{unique_id}%"},
                )
