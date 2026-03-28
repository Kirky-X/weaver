# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Neo4j sync enhancement — pending_sync flow and consistency checks."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core.db.models import PendingSync, PersistStatus
from modules.storage.pending_sync_repo import PendingSyncRepo


class TestPendingSyncRepo:
    """Integration tests for PendingSyncRepo."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool with async session support."""
        pool = MagicMock()
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        pool.session.return_value.__aenter__.return_value = mock_session
        pool.session.return_value.__aexit__.return_value = AsyncMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool):
        """Create PendingSyncRepo with mock pool."""
        return PendingSyncRepo(mock_pool)

    @pytest.mark.asyncio
    async def test_upsert_creates_new_record(self, repo, mock_pool):
        """Test upsert creates a new pending_sync record."""
        article_id = uuid4()
        payload = {"entities": [], "relations": []}

        # Mock no existing record
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        # Mock the add to return a record with id
        def mock_add(record):
            record.id = 123

        mock_pool.session.return_value.__aenter__.return_value.add.side_effect = mock_add

        record_id = await repo.upsert(article_id, "entity_relation", payload)

        assert record_id == 123
        mock_pool.session.return_value.__aenter__.return_value.commit.assert_called()

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_pending_record(self, repo, mock_pool):
        """Test upsert updates existing pending record (idempotent)."""
        article_id = uuid4()
        payload = {"entities": [{"name": "Updated"}]}

        # Mock existing pending record
        existing_record = MagicMock()
        existing_record.id = 42
        existing_record.payload = {"entities": []}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        record_id = await repo.upsert(article_id, "entity_relation", payload)

        assert record_id == 42
        assert existing_record.payload == payload
        assert existing_record.retry_count == 0
        mock_pool.session.return_value.__aenter__.return_value.commit.assert_called()

    @pytest.mark.asyncio
    async def test_get_pending_returns_pending_records(self, repo, mock_pool):
        """Test get_pending returns records ordered by created_at."""
        pending_records = [
            MagicMock(id=1, article_id=uuid4(), status="pending"),
            MagicMock(id=2, article_id=uuid4(), status="pending"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = pending_records
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        result = await repo.get_pending(limit=10)

        assert len(result) == 2
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

    @pytest.mark.asyncio
    async def test_mark_synced_updates_status(self, repo, mock_pool):
        """Test mark_synced sets status to synced and sets synced_at."""
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = MagicMock()

        await repo.mark_synced(42)

        mock_pool.session.return_value.__aenter__.return_value.execute.assert_called()
        mock_pool.session.return_value.__aenter__.return_value.commit.assert_called()

    @pytest.mark.asyncio
    async def test_mark_failed_increments_retry_count(self, repo, mock_pool):
        """Test mark_failed increments retry_count and sets error."""
        record = MagicMock()
        record.retry_count = 2
        record.status = "pending"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        await repo.mark_failed(42, "Connection refused")

        assert record.status == "failed"
        assert record.error == "Connection refused"
        assert record.retry_count == 3
        mock_pool.session.return_value.__aenter__.return_value.commit.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_old_synced_deletes_old_records(self, repo, mock_pool):
        """Test cleanup_old_synced deletes synced records older than N days."""
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        deleted = await repo.cleanup_old_synced(days=7)

        assert deleted == 5
        mock_pool.session.return_value.__aenter__.return_value.commit.assert_called()

    @pytest.mark.asyncio
    async def test_reconstruct_state_from_payload(self, repo):
        """Test reconstruct_state_from_payload returns correct structure."""
        payload = {
            "entities": [{"name": "Test Entity", "type": "PERSON"}],
            "relations": [{"source": "E1", "target": "E2", "relation_type": "WORKS_FOR"}],
            "cleaned": {"title": "Test Title", "body": "Test Body"},
            "category": "TECHNOLOGY",
            "score": 0.85,
            "merged_source_ids": [str(uuid4())],
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

    @pytest.mark.asyncio
    async def test_get_stale_pending_returns_old_pending_records(self, repo, mock_pool):
        """Test get_stale_pending returns pending records older than N hours."""
        stale_records = [
            MagicMock(id=1, article_id=uuid4(), status="pending"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = stale_records
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        result = await repo.get_stale_pending(hours=1)

        assert len(result) == 1
        mock_pool.session.return_value.__aenter__.return_value.execute.assert_called()


class TestContainerStartupSync:
    """Integration tests for Container startup sync trigger (Task 5.2)."""

    def test_startup_sync_in_startup_code(self):
        """Test that Container.startup() includes sync_pending_to_neo4j scheduling."""
        import inspect

        from container import Container

        source = inspect.getsource(Container.startup)
        assert "sync_pending_to_neo4j" in source
        assert "AsyncIOScheduler" in source
        assert "asyncio.create_task" in source


class TestSyncPendingToNeo4j:
    """Integration tests for sync_pending_to_neo4j job (Tasks 4.1, 4.6)."""

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        pending_sync_repo = MagicMock(spec=PendingSyncRepo)
        article_repo = MagicMock()
        vector_repo = MagicMock()
        neo4j_writer = MagicMock()
        postgres_pool = MagicMock()
        redis_client = MagicMock()

        return {
            "pending_sync_repo": pending_sync_repo,
            "article_repo": article_repo,
            "vector_repo": vector_repo,
            "neo4j_writer": neo4j_writer,
            "postgres_pool": postgres_pool,
            "redis_client": redis_client,
        }

    @pytest.mark.asyncio
    async def test_sync_pending_returns_zero_when_no_pending_records(self, mock_repos):
        """Test sync_pending_to_neo4j returns 0 when no pending records."""
        from modules.scheduler.jobs import SchedulerJobs

        mock_repos["pending_sync_repo"].get_pending.return_value = []

        jobs = SchedulerJobs(
            postgres_pool=mock_repos["postgres_pool"],
            redis_client=mock_repos["redis_client"],
            neo4j_writer=mock_repos["neo4j_writer"],
            vector_repo=mock_repos["vector_repo"],
            article_repo=mock_repos["article_repo"],
            source_authority_repo=MagicMock(),
            pending_sync_repo=mock_repos["pending_sync_repo"],
        )

        result = await jobs.sync_pending_to_neo4j()

        assert result == 0
        mock_repos["pending_sync_repo"].get_pending.assert_called_once_with(limit=100)

    @pytest.mark.asyncio
    async def test_sync_pending_processes_pending_records(self, mock_repos):
        """Test sync_pending_to_neo4j processes pending records successfully."""
        from modules.scheduler.jobs import SchedulerJobs

        article_id = uuid4()
        pending_record = MagicMock()
        pending_record.id = 1
        pending_record.article_id = article_id
        pending_record.payload = {
            "entities": [{"name": "Test", "type": "PERSON"}],
            "relations": [],
            "cleaned": {"title": "T", "body": "B"},
            "category": "TECHNOLOGY",
            "score": 0.5,
            "entity_temp_keys": {},
        }
        mock_repos["pending_sync_repo"].get_pending.return_value = [pending_record]
        mock_repos["pending_sync_repo"].reconstruct_state_from_payload.return_value = {
            "entities": [{"name": "Test", "type": "PERSON"}],
            "relations": [],
            "cleaned": {"title": "T", "body": "B"},
            "category": "TECHNOLOGY",
            "score": 0.5,
            "article_id": str(article_id),
        }
        mock_repos["neo4j_writer"].write = AsyncMock(return_value=[])
        mock_repos["article_repo"].update_persist_status = AsyncMock()
        mock_repos["pending_sync_repo"].mark_synced = AsyncMock()

        jobs = SchedulerJobs(
            postgres_pool=mock_repos["postgres_pool"],
            redis_client=mock_repos["redis_client"],
            neo4j_writer=mock_repos["neo4j_writer"],
            vector_repo=mock_repos["vector_repo"],
            article_repo=mock_repos["article_repo"],
            source_authority_repo=MagicMock(),
            pending_sync_repo=mock_repos["pending_sync_repo"],
        )

        result = await jobs.sync_pending_to_neo4j()

        assert result == 1
        mock_repos["neo4j_writer"].write.assert_called_once()
        mock_repos["article_repo"].update_persist_status.assert_called_once_with(
            article_id, PersistStatus.NEO4J_DONE
        )
        mock_repos["pending_sync_repo"].mark_synced.assert_called_once_with(1)


class TestConsistencyCheck:
    """Integration tests for consistency_check job (Tasks 4.3, 4.7)."""

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        return {
            "neo4j_writer": MagicMock(),
            "vector_repo": MagicMock(),
            "pending_sync_repo": MagicMock(),
            "postgres_pool": MagicMock(),
            "redis_client": MagicMock(),
        }

    @pytest.mark.asyncio
    async def test_consistency_check_detects_entity_mismatch(self, mock_repos):
        """Test consistency_check detects entity count mismatch between Neo4j and PG."""
        from modules.scheduler.jobs import SchedulerJobs

        # Neo4j has 500 entities, PG has 480
        mock_repos["neo4j_writer"].entity_repo.list_all_entity_ids = AsyncMock(
            return_value=[str(uuid4()) for _ in range(500)]
        )
        mock_repos["vector_repo"].count_entities_with_valid_neo4j_ids = AsyncMock(return_value=480)

        jobs = SchedulerJobs(
            postgres_pool=mock_repos["postgres_pool"],
            redis_client=mock_repos["redis_client"],
            neo4j_writer=mock_repos["neo4j_writer"],
            vector_repo=mock_repos["vector_repo"],
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=mock_repos["pending_sync_repo"],
        )

        result = await jobs.consistency_check()

        assert result["entity_mismatch"] is True
        assert result["neo4j_count"] == 500
        assert result["pg_count"] == 480

    @pytest.mark.asyncio
    async def test_consistency_check_detects_stale_pending_records(self, mock_repos):
        """Test consistency_check detects stale pending records."""
        from modules.scheduler.jobs import SchedulerJobs

        mock_repos["neo4j_writer"].entity_repo.list_all_entity_ids = AsyncMock(
            return_value=[str(uuid4()) for _ in range(100)]
        )
        mock_repos["vector_repo"].count_entities_with_valid_neo4j_ids = AsyncMock(return_value=100)
        mock_repos["vector_repo"].get_entity_vectors_with_temp_keys = AsyncMock(return_value=[])

        stale_record = MagicMock()
        stale_record.id = 1
        stale_record.article_id = uuid4()
        stale_record.created_at = datetime.now(UTC) - timedelta(hours=2)
        mock_repos["pending_sync_repo"].get_stale_pending = AsyncMock(return_value=[stale_record])

        jobs = SchedulerJobs(
            postgres_pool=mock_repos["postgres_pool"],
            redis_client=mock_repos["redis_client"],
            neo4j_writer=mock_repos["neo4j_writer"],
            vector_repo=mock_repos["vector_repo"],
            article_repo=MagicMock(),
            source_authority_repo=MagicMock(),
            pending_sync_repo=mock_repos["pending_sync_repo"],
        )

        result = await jobs.consistency_check()

        assert len(result["stale_pending"]) == 1


class TestRetryNeo4jWritesWithPendingSync:
    """Integration tests for retry_neo4j_writes preferring pending_sync (Task 24)."""

    @pytest.mark.asyncio
    async def test_pending_sync_repo_has_get_by_article_id_method(self):
        """Test that PendingSyncRepo has get_by_article_id method."""
        assert hasattr(PendingSyncRepo(MagicMock()), "get_by_article_id")

    @pytest.mark.asyncio
    async def test_pending_sync_repo_get_by_article_id_returns_record(self):
        """Test that PendingSyncRepo.get_by_article_id returns the correct record."""
        pool = MagicMock()
        repo = PendingSyncRepo(pool)

        article_id = uuid4()
        mock_record = MagicMock()
        mock_record.payload = {"entities": [], "relations": []}

        # Setup mock to return the record
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        result = await repo.get_by_article_id(article_id)

        assert result == mock_record
