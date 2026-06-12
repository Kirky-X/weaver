# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for SagaLogRepo repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.saga.repository import SagaLogRepo


@pytest.fixture
def mock_pool():
    """Create a mock RelationalPool."""
    pool = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    pool.session.return_value = session
    return pool, session


@pytest.fixture
def repo(mock_pool):
    """Create a SagaLogRepo instance."""
    pool, _ = mock_pool
    return SagaLogRepo(pool)


class TestSagaLogRepoCreate:
    """Tests for SagaLogRepo.create."""

    @pytest.mark.asyncio
    async def test_create_returns_uuid(self, repo, mock_pool):
        _, session = mock_pool
        log_id = await repo.create(
            saga_id=uuid.uuid4(),
            article_id=uuid.uuid4(),
            step_name="pg_insert",
            step_status="started",
        )
        assert isinstance(log_id, uuid.UUID)
        session.add.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_compensation_data(self, repo, mock_pool):
        _, session = mock_pool
        compensation = {"type": "postgres", "operation": "insert"}
        log_id = await repo.create(
            saga_id=uuid.uuid4(),
            article_id=uuid.uuid4(),
            step_name="pg_insert",
            step_status="started",
            compensation_data=compensation,
        )
        assert isinstance(log_id, uuid.UUID)
        added_obj = session.add.call_args[0][0]
        assert added_obj.compensation_data == compensation


class TestSagaLogRepoUpdate:
    """Tests for SagaLogRepo.update_status."""

    @pytest.mark.asyncio
    async def test_update_status_sets_completed_at(self, repo, mock_pool):
        _, session = mock_pool
        log_id = uuid.uuid4()
        await repo.update_status(log_id, "completed")
        session.execute.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, repo, mock_pool):
        _, session = mock_pool
        log_id = uuid.uuid4()
        await repo.update_status(log_id, "failed", error_message="Connection refused")
        session.execute.assert_called_once()


class TestSagaLogRepoIncrementRetry:
    """Tests for SagaLogRepo.increment_retry."""

    @pytest.mark.asyncio
    async def test_increment_retry(self, repo, mock_pool):
        _, session = mock_pool
        await repo.increment_retry(uuid.uuid4())
        session.execute.assert_called_once()
        session.commit.assert_called_once()


class TestSagaLogRepoQueries:
    """Tests for SagaLogRepo query methods."""

    @pytest.mark.asyncio
    async def test_get_by_saga_id(self, repo, mock_pool):
        _, session = mock_pool
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await repo.get_by_saga_id(uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_get_by_article_id(self, repo, mock_pool):
        _, session = mock_pool
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await repo.get_by_article_id(uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_get_failed_logs(self, repo, mock_pool):
        _, session = mock_pool
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await repo.get_failed_logs()
        assert result == []


class TestSagaLogRepoBatchCreate:
    """Tests for SagaLogRepo.batch_create."""

    @pytest.mark.asyncio
    async def test_batch_create_empty_list(self, repo, mock_pool):
        _, session = mock_pool
        await repo.batch_create([])
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_create_multiple_entries(self, repo, mock_pool):
        _, session = mock_pool
        saga_id = uuid.uuid4()
        article_id = uuid.uuid4()
        entries = [
            {
                "id": uuid.uuid4(),
                "saga_id": saga_id,
                "article_id": article_id,
                "step_name": "pg_insert",
                "step_status": "started",
                "started_at": datetime.now(UTC),
            },
            {
                "id": uuid.uuid4(),
                "saga_id": saga_id,
                "article_id": article_id,
                "step_name": "neo4j_write",
                "step_status": "started",
                "started_at": datetime.now(UTC),
            },
        ]
        await repo.batch_create(entries)
        assert session.add.call_count == 2
        session.commit.assert_called_once()


class TestSagaLogRepoArchive:
    """Tests for SagaLogRepo.archive_old_logs."""

    @pytest.mark.asyncio
    async def test_archive_old_logs(self, repo, mock_pool):
        _, session = mock_pool
        mock_result = MagicMock()
        mock_result.rowcount = 5
        session.execute.return_value = mock_result

        deleted = await repo.archive_old_logs(retention_days=30)
        assert deleted == 5

    @pytest.mark.asyncio
    async def test_archive_with_custom_retention(self, repo, mock_pool):
        _, session = mock_pool
        mock_result = MagicMock()
        mock_result.rowcount = 0
        session.execute.return_value = mock_result

        deleted = await repo.archive_old_logs(retention_days=7)
        assert deleted == 0


class TestSagaLogRepoCompensationData:
    """Tests for SagaLogRepo.get_completed_compensation_data."""

    @pytest.mark.asyncio
    async def test_get_completed_compensation_data(self, repo, mock_pool):
        _, session = mock_pool
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [
            {"type": "postgres", "operation": "insert"},
            {"type": "neo4j", "operation": "entity_create"},
        ]
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await repo.get_completed_compensation_data(uuid.uuid4())
        assert len(result) == 2
        assert result[0]["type"] == "postgres"

    @pytest.mark.asyncio
    async def test_get_completed_compensation_data_empty(self, repo, mock_pool):
        _, session = mock_pool
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await repo.get_completed_compensation_data(uuid.uuid4())
        assert result == []
