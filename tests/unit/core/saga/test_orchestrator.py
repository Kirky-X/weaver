# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for SagaOrchestrator."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.saga.orchestrator import (
    SagaOrchestrator,
    SagaResult,
    SagaStatus,
    SagaStep,
)


@pytest.fixture
def mock_log_repo():
    """Create a mock SagaLogRepo."""
    repo = AsyncMock()
    repo.create.return_value = uuid.uuid4()
    return repo


@pytest.fixture
def orchestrator(mock_log_repo):
    """Create a SagaOrchestrator with mock dependencies."""
    return SagaOrchestrator(
        log_repo=mock_log_repo,
        timeout_seconds=5,
        max_retries=2,
        retry_base_delay=0.01,
        retry_max_delay=0.1,
    )


class TestSagaOrchestratorStart:
    """Tests for SagaOrchestrator.start_saga."""

    @pytest.mark.asyncio
    async def test_successful_saga(self, orchestrator, mock_log_repo):
        """Test a saga where all steps succeed."""
        step1_executed = False
        step2_executed = False

        async def step1():
            nonlocal step1_executed
            step1_executed = True

        async def step2():
            nonlocal step2_executed
            step2_executed = True

        steps = [
            SagaStep(
                name="pg_insert",
                execute=step1,
                compensation_data={"type": "postgres", "step_name": "pg_insert"},
            ),
            SagaStep(
                name="neo4j_write",
                execute=step2,
                compensation_data={"type": "neo4j", "step_name": "neo4j_write"},
            ),
        ]

        result = await orchestrator.start_saga(uuid.uuid4(), steps)

        assert result.status == SagaStatus.COMPLETED
        assert step1_executed is True
        assert step2_executed is True
        assert "pg_insert" in result.completed_steps
        assert "neo4j_write" in result.completed_steps

    @pytest.mark.asyncio
    async def test_saga_with_no_steps(self, orchestrator):
        """Test a saga with no steps completes immediately."""
        result = await orchestrator.start_saga(uuid.uuid4(), [])
        assert result.status == SagaStatus.COMPLETED
        assert result.completed_steps == []

    @pytest.mark.asyncio
    async def test_saga_returns_saga_id(self, orchestrator):
        """Test that saga result contains a valid saga_id."""
        result = await orchestrator.start_saga(uuid.uuid4(), [])
        assert isinstance(result.saga_id, uuid.UUID)


class TestSagaOrchestratorFailure:
    """Tests for saga failure and compensation."""

    @pytest.mark.asyncio
    async def test_step_failure_triggers_compensation(self, orchestrator, mock_log_repo):
        """Test that step failure triggers compensation of completed steps."""
        step1_executed = False

        async def step1():
            nonlocal step1_executed
            step1_executed = True

        async def step2():
            raise RuntimeError("Neo4j connection failed")

        steps = [
            SagaStep(
                name="pg_insert",
                execute=step1,
                compensation_data={
                    "type": "postgres",
                    "step_name": "pg_insert",
                    "saga_id": "s1",
                    "article_id": "a1",
                    "operation": "insert",
                },
            ),
            SagaStep(name="neo4j_write", execute=step2),
        ]

        with patch.object(
            orchestrator._compensation_executor, "execute_compensations", new_callable=AsyncMock
        ) as mock_comp:
            mock_comp.return_value = MagicMock(
                success=True, completed_steps=["pg_insert"], failed_steps=[]
            )
            result = await orchestrator.start_saga(uuid.uuid4(), steps)

        assert result.status == SagaStatus.COMPENSATED
        assert result.failed_step == "neo4j_write"
        mock_comp.assert_called_once()

    @pytest.mark.asyncio
    async def test_compensation_failure_results_in_failed(self, orchestrator, mock_log_repo):
        """Test that compensation failure results in FAILED status."""

        async def step1():
            pass

        async def step2():
            raise RuntimeError("Step 2 failed")

        steps = [
            SagaStep(
                name="pg_insert",
                execute=step1,
                compensation_data={
                    "type": "postgres",
                    "step_name": "pg_insert",
                    "saga_id": "s1",
                    "article_id": "a1",
                    "operation": "insert",
                },
            ),
            SagaStep(name="neo4j_write", execute=step2),
        ]

        with patch.object(
            orchestrator._compensation_executor, "execute_compensations", new_callable=AsyncMock
        ) as mock_comp:
            mock_comp.return_value = MagicMock(
                success=False,
                completed_steps=[],
                failed_steps=[{"step_name": "pg_insert", "error": "compensation failed"}],
            )
            result = await orchestrator.start_saga(uuid.uuid4(), steps)

        assert result.status == SagaStatus.FAILED


class TestSagaOrchestratorRetry:
    """Tests for step retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_step_retries_on_failure(self, orchestrator, mock_log_repo):
        """Test that a step is retried on failure."""
        call_count = 0

        async def flaky_step():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Transient error")

        steps = [SagaStep(name="flaky_step", execute=flaky_step)]

        result = await orchestrator.start_saga(uuid.uuid4(), steps)

        assert result.status == SagaStatus.COMPLETED
        assert call_count == 3  # First attempt + 2 retries

    @pytest.mark.asyncio
    async def test_step_fails_after_max_retries(self, orchestrator, mock_log_repo):
        """Test that step fails after max retries exhausted."""

        async def always_fails():
            raise RuntimeError("Persistent error")

        steps = [SagaStep(name="always_fails", execute=always_fails)]

        with patch.object(
            orchestrator._compensation_executor, "execute_compensations", new_callable=AsyncMock
        ) as mock_comp:
            mock_comp.return_value = MagicMock(success=True, completed_steps=[], failed_steps=[])
            result = await orchestrator.start_saga(uuid.uuid4(), steps)

        assert result.failed_step == "always_fails"
        assert result.status == SagaStatus.COMPENSATED


class TestSagaOrchestratorTimeout:
    """Tests for saga timeout handling."""

    @pytest.mark.asyncio
    async def test_saga_timeout(self):
        """Test that saga times out after configured duration."""
        mock_repo = AsyncMock()
        mock_repo.create.return_value = uuid.uuid4()

        orchestrator = SagaOrchestrator(
            log_repo=mock_repo,
            timeout_seconds=0,  # Immediate timeout
            max_retries=0,
        )

        import asyncio

        async def slow_step():
            await asyncio.sleep(10)

        steps = [SagaStep(name="slow_step", execute=slow_step)]

        with patch.object(
            orchestrator._compensation_executor, "execute_compensations", new_callable=AsyncMock
        ) as mock_comp:
            mock_comp.return_value = MagicMock(success=True, completed_steps=[], failed_steps=[])
            result = await orchestrator.start_saga(uuid.uuid4(), steps)

        assert result.status == SagaStatus.TIMED_OUT


class TestSagaOrchestratorManualCompensation:
    """Tests for manual compensation."""

    @pytest.mark.asyncio
    async def test_compensate_saga(self, orchestrator, mock_log_repo):
        """Test manual compensation of a saga."""
        saga_id = uuid.uuid4()
        mock_log_repo.get_completed_compensation_data.return_value = [
            {"type": "postgres", "step_name": "pg_insert"},
        ]

        with patch.object(
            orchestrator._compensation_executor, "execute_compensations", new_callable=AsyncMock
        ) as mock_comp:
            mock_comp.return_value = MagicMock(
                success=True, completed_steps=["pg_insert"], failed_steps=[]
            )
            result = await orchestrator.compensate_saga(saga_id)

        assert result.status == SagaStatus.COMPENSATED

    @pytest.mark.asyncio
    async def test_compensate_saga_no_completed_steps(self, orchestrator, mock_log_repo):
        """Test manual compensation when no steps completed."""
        saga_id = uuid.uuid4()
        mock_log_repo.get_completed_compensation_data.return_value = []

        result = await orchestrator.compensate_saga(saga_id)

        assert result.status == SagaStatus.COMPENSATED


class TestSagaOrchestratorStatus:
    """Tests for saga status query."""

    @pytest.mark.asyncio
    async def test_get_saga_status_unknown(self, orchestrator, mock_log_repo):
        """Test status query for unknown saga."""
        mock_log_repo.get_by_saga_id.return_value = []
        saga_id = uuid.uuid4()

        status = await orchestrator.get_saga_status(saga_id)

        assert status["status"] == "unknown"
        assert status["steps"] == []

    @pytest.mark.asyncio
    async def test_get_saga_status_completed(self, orchestrator, mock_log_repo):
        """Test status query for completed saga."""
        mock_entry = MagicMock()
        mock_entry.step_name = "pg_insert"
        mock_entry.step_status = "completed"
        mock_entry.started_at = datetime.now(UTC)
        mock_entry.completed_at = datetime.now(UTC)
        mock_entry.error_message = None
        mock_entry.retry_count = 0
        mock_log_repo.get_by_saga_id.return_value = [mock_entry]

        status = await orchestrator.get_saga_status(uuid.uuid4())

        assert status["status"] == "completed"
        assert len(status["steps"]) == 1


class TestSagaResult:
    """Tests for SagaResult dataclass."""

    def test_completed_result(self):
        result = SagaResult(
            saga_id=uuid.uuid4(),
            status=SagaStatus.COMPLETED,
            completed_steps=["step1", "step2"],
        )
        assert result.status == SagaStatus.COMPLETED
        assert result.failed_step is None
        assert result.error is None

    def test_failed_result(self):
        result = SagaResult(
            saga_id=uuid.uuid4(),
            status=SagaStatus.FAILED,
            failed_step="step2",
            error="Connection refused",
        )
        assert result.status == SagaStatus.FAILED
        assert result.failed_step == "step2"
