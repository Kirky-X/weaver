# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Saga API endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.saga.orchestrator import SagaResult, SagaStatus


@pytest.fixture
def mock_orchestrator():
    """Create a mock SagaOrchestrator."""
    orchestrator = AsyncMock()
    return orchestrator


@pytest.fixture
def client(mock_orchestrator):
    """Create a test client with mocked saga orchestrator."""
    with patch(
        "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
    ):
        from main import app

        with TestClient(app) as c:
            yield c


class TestGetSagaStatus:
    """Tests for GET /api/v1/saga/{saga_id}."""

    @pytest.mark.asyncio
    async def test_get_saga_status_found(self, mock_orchestrator):
        saga_id = uuid.uuid4()
        mock_orchestrator.get_saga_status.return_value = {
            "saga_id": str(saga_id),
            "status": "completed",
            "steps": [
                {
                    "step_name": "pg_insert",
                    "step_status": "completed",
                    "started_at": datetime.now(UTC).isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error_message": None,
                    "retry_count": 0,
                }
            ],
        }

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from api.endpoints.saga import get_saga_status

            result = await get_saga_status(saga_id)

        assert result["status"] == "completed"
        assert len(result["steps"]) == 1

    @pytest.mark.asyncio
    async def test_get_saga_status_not_found(self, mock_orchestrator):
        saga_id = uuid.uuid4()
        mock_orchestrator.get_saga_status.return_value = {
            "saga_id": str(saga_id),
            "status": "unknown",
            "steps": [],
        }

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from fastapi import HTTPException

            from api.endpoints.saga import get_saga_status

            with pytest.raises(HTTPException) as exc_info:
                await get_saga_status(saga_id)
            assert exc_info.value.status_code == 404


class TestCompensateSaga:
    """Tests for POST /api/v1/saga/{saga_id}/compensate."""

    @pytest.mark.asyncio
    async def test_compensate_saga_success(self, mock_orchestrator):
        saga_id = uuid.uuid4()
        mock_result = SagaResult(
            saga_id=saga_id,
            status=SagaStatus.COMPENSATED,
            compensation_result=MagicMock(
                completed_steps=["pg_insert"],
                failed_steps=[],
            ),
        )
        mock_orchestrator.compensate_saga.return_value = mock_result

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from api.endpoints.saga import compensate_saga

            result = await compensate_saga(saga_id)

        assert result["status"] == "compensated"

    @pytest.mark.asyncio
    async def test_compensate_saga_failure(self, mock_orchestrator):
        saga_id = uuid.uuid4()
        mock_result = SagaResult(
            saga_id=saga_id,
            status=SagaStatus.FAILED,
            compensation_result=MagicMock(
                completed_steps=[],
                failed_steps=[{"step_name": "pg_insert", "error": "rollback failed"}],
            ),
        )
        mock_orchestrator.compensate_saga.return_value = mock_result

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from fastapi import HTTPException

            from api.endpoints.saga import compensate_saga

            with pytest.raises(HTTPException) as exc_info:
                await compensate_saga(saga_id)
            assert exc_info.value.status_code == 500


class TestRetrySaga:
    """Tests for POST /api/v1/saga/{saga_id}/retry."""

    @pytest.mark.asyncio
    async def test_retry_saga_success(self, mock_orchestrator):
        saga_id = uuid.uuid4()
        article_id = uuid.uuid4()

        mock_orchestrator.get_saga_status.return_value = {
            "saga_id": str(saga_id),
            "status": "failed",
            "steps": [
                {
                    "step_name": "pg_insert",
                    "step_status": "completed",
                    "started_at": datetime.now(UTC).isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error_message": None,
                    "retry_count": 0,
                }
            ],
        }

        mock_log_repo = AsyncMock()
        mock_entry = MagicMock()
        mock_entry.article_id = article_id
        mock_log_repo.get_by_saga_id.return_value = [mock_entry]
        mock_orchestrator._log_repo = mock_log_repo

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from api.endpoints.saga import retry_saga

            result = await retry_saga(saga_id)

        assert result["article_id"] == str(article_id)
        assert result["previous_status"] == "failed"

    @pytest.mark.asyncio
    async def test_retry_saga_not_found(self, mock_orchestrator):
        saga_id = uuid.uuid4()
        mock_orchestrator.get_saga_status.return_value = {
            "saga_id": str(saga_id),
            "status": "unknown",
            "steps": [],
        }

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from fastapi import HTTPException

            from api.endpoints.saga import retry_saga

            with pytest.raises(HTTPException) as exc_info:
                await retry_saga(saga_id)
            assert exc_info.value.status_code == 404


class TestListFailedSagas:
    """Tests for GET /api/v1/saga/failed/list."""

    @pytest.mark.asyncio
    async def test_list_failed_sagas(self, mock_orchestrator):
        mock_log_repo = AsyncMock()
        mock_entry = MagicMock()
        mock_entry.id = uuid.uuid4()
        mock_entry.saga_id = uuid.uuid4()
        mock_entry.article_id = uuid.uuid4()
        mock_entry.step_name = "pg_insert"
        mock_entry.step_status = "failed"
        mock_entry.error_message = "Connection refused"
        mock_entry.retry_count = 3
        mock_log_repo.get_failed_logs.return_value = [mock_entry]
        mock_orchestrator._log_repo = mock_log_repo

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from api.endpoints.saga import list_failed_sagas

            result = await list_failed_sagas(limit=10)

        assert result["failed_count"] == 1
        assert len(result["entries"]) == 1

    @pytest.mark.asyncio
    async def test_list_failed_sagas_limit_capped(self, mock_orchestrator):
        mock_log_repo = AsyncMock()
        mock_log_repo.get_failed_logs.return_value = []
        mock_orchestrator._log_repo = mock_log_repo

        with patch(
            "api.endpoints.saga.Endpoints.get_saga_orchestrator", return_value=mock_orchestrator
        ):
            from api.endpoints.saga import list_failed_sagas

            result = await list_failed_sagas(limit=500)

        # Limit should be capped to 200
        mock_log_repo.get_failed_logs.assert_called_once_with(limit=200)
