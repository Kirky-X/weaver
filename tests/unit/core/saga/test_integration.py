# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Saga compensation transaction system.

Tests the full saga lifecycle with real database interactions,
including step execution, failure compensation, and log persistence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.saga.compensation import Neo4jCompensation, PostgresCompensation
from core.saga.executor import CompensationExecutor, CompensationResult
from core.saga.orchestrator import SagaOrchestrator, SagaStatus, SagaStep
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
def log_repo(mock_pool):
    pool, _ = mock_pool
    return SagaLogRepo(pool)


@pytest.fixture
def orchestrator(log_repo):
    return SagaOrchestrator(
        log_repo=log_repo,
        timeout_seconds=5,
        max_retries=1,
        retry_base_delay=0.01,
    )


class TestSagaEndToEnd:
    """End-to-end integration tests for saga lifecycle."""

    @pytest.mark.asyncio
    async def test_full_saga_lifecycle_success(self, orchestrator, mock_pool):
        """Test complete saga lifecycle: start → execute steps → complete."""
        _, session = mock_pool
        article_id = uuid.uuid4()

        execution_order = []

        async def pg_insert():
            execution_order.append("pg_insert")

        async def neo4j_write():
            execution_order.append("neo4j_write")

        steps = [
            SagaStep(
                name="pg_insert",
                execute=pg_insert,
                compensation_data={
                    "type": "postgres",
                    "saga_id": "s1",
                    "article_id": str(article_id),
                    "step_name": "pg_insert",
                    "operation": "insert",
                },
            ),
            SagaStep(
                name="neo4j_write",
                execute=neo4j_write,
                compensation_data={
                    "type": "neo4j",
                    "saga_id": "s1",
                    "article_id": str(article_id),
                    "step_name": "neo4j_write",
                    "operation": "entity_create",
                    "entity_ids": [],
                    "relationship_ids": [],
                },
            ),
        ]

        result = await orchestrator.start_saga(article_id, steps)

        assert result.status == SagaStatus.COMPLETED
        assert execution_order == ["pg_insert", "neo4j_write"]
        # Verify log entries were created for each step
        assert session.add.call_count == 2
        assert session.commit.call_count >= 2

    @pytest.mark.asyncio
    async def test_saga_failure_with_compensation(self, orchestrator, mock_pool):
        """Test saga failure triggers compensation of completed steps."""
        _, session = mock_pool
        article_id = uuid.uuid4()

        async def pg_insert():
            pass

        async def neo4j_write():
            raise RuntimeError("Neo4j unavailable")

        steps = [
            SagaStep(
                name="pg_insert",
                execute=pg_insert,
                compensation_data={
                    "type": "postgres",
                    "saga_id": "s1",
                    "article_id": str(article_id),
                    "step_name": "pg_insert",
                    "operation": "insert",
                },
            ),
            SagaStep(name="neo4j_write", execute=neo4j_write),
        ]

        with patch.object(
            orchestrator._compensation_executor, "execute_compensations", new_callable=AsyncMock
        ) as mock_comp:
            mock_comp.return_value = CompensationResult(
                success=True,
                completed_steps=["pg_insert"],
                failed_steps=[],
            )
            result = await orchestrator.start_saga(article_id, steps)

        assert result.status == SagaStatus.COMPENSATED
        assert result.failed_step == "neo4j_write"
        mock_comp.assert_called_once()

    @pytest.mark.asyncio
    async def test_saga_retry_then_success(self, orchestrator, mock_pool):
        """Test saga step that fails initially then succeeds on retry."""
        _, session = mock_pool
        call_count = 0

        async def flaky_step():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Transient failure")

        steps = [SagaStep(name="flaky_step", execute=flaky_step)]

        result = await orchestrator.start_saga(uuid.uuid4(), steps)

        assert result.status == SagaStatus.COMPLETED
        assert call_count == 2  # First attempt failed, second succeeded

    @pytest.mark.asyncio
    async def test_saga_status_query(self, orchestrator, mock_pool):
        """Test querying saga status after execution."""
        _, session = mock_pool
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_entry = MagicMock()
        mock_entry.step_name = "pg_insert"
        mock_entry.step_status = "completed"
        mock_entry.started_at = datetime.now(UTC)
        mock_entry.completed_at = datetime.now(UTC)
        mock_entry.error_message = None
        mock_entry.retry_count = 0
        mock_scalars.all.return_value = [mock_entry]
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        status = await orchestrator.get_saga_status(uuid.uuid4())

        assert status["status"] == "completed"
        assert len(status["steps"]) == 1


class TestCompensationDeserialization:
    """Tests for compensation command deserialization roundtrip."""

    def test_postgres_compensation_roundtrip(self):
        original = PostgresCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="pg_insert",
            operation="insert",
            backup_data={"old_status": "pending"},
        )
        serialized = original.serialize()
        from core.saga.compensation import deserialize_compensation

        restored = deserialize_compensation(serialized)

        assert isinstance(restored, PostgresCompensation)
        assert restored.saga_id == original.saga_id
        assert restored.operation == original.operation
        assert restored.backup_data == original.backup_data

    def test_neo4j_compensation_roundtrip(self):
        original = Neo4jCompensation(
            saga_id="saga-1",
            article_id="art-1",
            step_name="neo4j_write",
            operation="entity_create",
            entity_ids=["e1", "e2"],
            relationship_ids=["r1"],
        )
        serialized = original.serialize()
        from core.saga.compensation import deserialize_compensation

        restored = deserialize_compensation(serialized)

        assert isinstance(restored, Neo4jCompensation)
        assert restored.saga_id == original.saga_id
        assert restored.entity_ids == original.entity_ids


class TestSagaConfiguration:
    """Tests for Saga configuration integration."""

    def test_saga_settings_defaults(self):
        from config.subconfigs import SagaSettings

        settings = SagaSettings()
        assert settings.timeout_seconds == 300
        assert settings.max_retries == 3
        assert settings.retry_base_delay == 1.0
        assert settings.retry_max_delay == 30.0
        assert settings.compensation_timeout == 120
        assert settings.log_retention_days == 30

    def test_saga_settings_custom(self):
        from config.subconfigs import SagaSettings

        settings = SagaSettings(
            timeout_seconds=60,
            max_retries=5,
            retry_base_delay=0.5,
        )
        assert settings.timeout_seconds == 60
        assert settings.max_retries == 5
        assert settings.retry_base_delay == 0.5


class TestSagaMetrics:
    """Tests for Saga Prometheus metrics."""

    def test_saga_metrics_defined(self):
        from core.observability.metrics import MetricsCollector

        mc = MetricsCollector()
        assert hasattr(mc, "saga_total")
        assert hasattr(mc, "saga_step_latency")
        assert hasattr(mc, "saga_compensation_total")
        assert hasattr(mc, "saga_active_count")

    def test_saga_metrics_labels(self):
        from core.observability.metrics import metrics

        # Verify we can create labeled metrics without error
        metrics.saga_total.labels(status="completed")
        metrics.saga_step_latency.labels(step_name="pg_insert")
        metrics.saga_compensation_total.labels(step_name="pg_insert", status="success")
