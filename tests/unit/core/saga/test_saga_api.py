# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for Saga API endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.saga.orchestrator import SagaResult, SagaStatus


@pytest.fixture
def mock_orchestrator():
    """Create a mock SagaOrchestrator."""
    orchestrator = AsyncMock()
    return orchestrator


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

        from api.endpoints.saga import get_saga_status

        result = await get_saga_status(saga_id, orchestrator=mock_orchestrator)

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

        from fastapi import HTTPException

        from api.endpoints.saga import get_saga_status

        with pytest.raises(HTTPException) as exc_info:
            await get_saga_status(saga_id, orchestrator=mock_orchestrator)
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

        from api.endpoints.saga import compensate_saga

        result = await compensate_saga(saga_id, orchestrator=mock_orchestrator)

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

        from fastapi import HTTPException

        from api.endpoints.saga import compensate_saga

        with pytest.raises(HTTPException) as exc_info:
            await compensate_saga(saga_id, orchestrator=mock_orchestrator)
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

        mock_entry = MagicMock()
        mock_entry.article_id = article_id
        mock_orchestrator.get_saga_logs = AsyncMock(return_value=[mock_entry])

        from api.endpoints.saga import retry_saga

        result = await retry_saga(saga_id, orchestrator=mock_orchestrator)

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

        from fastapi import HTTPException

        from api.endpoints.saga import retry_saga

        with pytest.raises(HTTPException) as exc_info:
            await retry_saga(saga_id, orchestrator=mock_orchestrator)
        assert exc_info.value.status_code == 404


class TestListFailedSagas:
    """Tests for GET /api/v1/saga/failed/list."""

    @pytest.mark.asyncio
    async def test_list_failed_sagas(self, mock_orchestrator):
        mock_entry = MagicMock()
        mock_entry.id = uuid.uuid4()
        mock_entry.saga_id = uuid.uuid4()
        mock_entry.article_id = uuid.uuid4()
        mock_entry.step_name = "pg_insert"
        mock_entry.step_status = "failed"
        mock_entry.error_message = "Connection refused"
        mock_entry.retry_count = 3
        mock_orchestrator.get_failed_saga_logs = AsyncMock(return_value=[mock_entry])

        from api.endpoints.saga import list_failed_sagas

        result = await list_failed_sagas(limit=10, orchestrator=mock_orchestrator)

        assert result["failed_count"] == 1
        assert len(result["entries"]) == 1

    @pytest.mark.asyncio
    async def test_list_failed_sagas_limit_passthrough(self, mock_orchestrator):
        """Limit is validated by FastAPI Query(ge=1, le=200); function passes it through."""
        mock_orchestrator.get_failed_saga_logs = AsyncMock(return_value=[])

        from api.endpoints.saga import list_failed_sagas

        # Function trusts framework validation; passes limit as-is
        result = await list_failed_sagas(limit=100, orchestrator=mock_orchestrator)

        mock_orchestrator.get_failed_saga_logs.assert_called_once_with(limit=100)
        assert result["failed_count"] == 0
