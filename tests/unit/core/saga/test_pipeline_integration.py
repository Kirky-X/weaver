# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for Pipeline-Saga integration."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    """Create a SagaLogRepo with mock pool."""
    pool, _ = mock_pool
    return SagaLogRepo(pool)


@pytest.fixture
def orchestrator(log_repo):
    """Create a SagaOrchestrator for pipeline integration tests."""
    return SagaOrchestrator(
        log_repo=log_repo,
        timeout_seconds=5,
        max_retries=1,
        retry_base_delay=0.01,
    )


class TestPipelineSagaIntegration:
    """Tests for Pipeline steps mapped to Saga steps."""

    @pytest.mark.asyncio
    async def test_pg_and_neo4j_steps_succeed(self, orchestrator):
        """Test that PostgreSQL + Neo4j saga steps complete successfully."""
        article_id = uuid.uuid4()

        pg_done = False
        neo4j_done = False

        async def pg_insert():
            nonlocal pg_done
            pg_done = True

        async def neo4j_write():
            nonlocal neo4j_done
            neo4j_done = True

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
        assert pg_done is True
        assert neo4j_done is True
        assert "pg_insert" in result.completed_steps
        assert "neo4j_write" in result.completed_steps

    @pytest.mark.asyncio
    async def test_neo4j_failure_triggers_pg_compensation(self, orchestrator):
        """Test that Neo4j failure triggers PostgreSQL rollback."""
        article_id = uuid.uuid4()

        async def pg_insert():
            pass

        async def neo4j_write():
            raise RuntimeError("Neo4j connection refused")

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
            ),
        ]

        with patch.object(
            orchestrator._compensation_executor, "execute_compensations", new_callable=AsyncMock
        ) as mock_comp:
            mock_comp.return_value = MagicMock(
                success=True,
                completed_steps=["pg_insert"],
                failed_steps=[],
            )
            result = await orchestrator.start_saga(article_id, steps)

        assert result.status == SagaStatus.COMPENSATED
        assert result.failed_step == "neo4j_write"
        # Verify compensation was called with pg_insert data
        call_args = mock_comp.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0]["step_name"] == "pg_insert"

    @pytest.mark.asyncio
    async def test_saga_with_persist_status_integration(self, mock_pool):
        """Test that saga steps can update PersistStatus."""
        from core.db import PersistStatus

        # Verify Saga states are accessible
        assert PersistStatus.SAGA_STARTED.value == "saga_started"
        assert PersistStatus.SAGA_PG_WRITING.value == "saga_pg_writing"
        assert PersistStatus.SAGA_NEO4J_WRITING.value == "saga_neo4j_writing"
        assert PersistStatus.SAGA_COMPLETED.value == "saga_completed"
        assert PersistStatus.SAGA_COMPENSATING.value == "saga_compensating"
        assert PersistStatus.SAGA_COMPENSATED.value == "saga_compensated"

        # Verify transition from PENDING to SAGA_STARTED
        assert PersistStatus.is_valid_transition(PersistStatus.PENDING, PersistStatus.SAGA_STARTED)
        # Verify SAGA_COMPLETED is terminal
        assert PersistStatus.is_terminal(PersistStatus.SAGA_COMPLETED)
        # Verify SAGA_COMPENSATED allows retry
        assert PersistStatus.allows_retry(PersistStatus.SAGA_COMPENSATED)


class TestContainerSagaIntegration:
    """Tests for Container providing SagaOrchestrator."""

    def test_container_has_saga_orchestrator_property(self):
        """Test that Container class has saga_orchestrator property."""
        from container import Container

        assert hasattr(Container, "saga_orchestrator")
        assert callable(Container.saga_orchestrator)
