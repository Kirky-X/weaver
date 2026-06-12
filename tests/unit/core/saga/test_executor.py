# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for CompensationExecutor."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.saga.executor import CompensationExecutor, CompensationResult


@pytest.fixture
def executor():
    """Create a CompensationExecutor with short timeout for tests."""
    return CompensationExecutor(timeout_seconds=2)


class TestCompensationExecutorReverseOrder:
    """Tests for reverse-order compensation execution."""

    @pytest.mark.asyncio
    async def test_empty_compensation_list(self, executor):
        result = await executor.execute_compensations([])
        assert result.success is True
        assert result.completed_steps == []
        assert result.failed_steps == []

    @pytest.mark.asyncio
    async def test_single_compensation(self, executor):
        comp_data = {
            "type": "postgres",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "pg_insert",
            "operation": "insert",
        }
        with patch("core.saga.executor.deserialize_compensation") as mock_deserialize:
            mock_cmd = AsyncMock()
            mock_deserialize.return_value = mock_cmd

            result = await executor.execute_compensations([comp_data])

        assert result.success is True
        assert "pg_insert" in result.completed_steps
        mock_cmd.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_compensations_in_reverse_order(self, executor):
        """Compensations should execute in reverse order."""
        comp_data_list = [
            {
                "type": "postgres",
                "saga_id": "saga-1",
                "article_id": "art-1",
                "step_name": "pg_insert",
                "operation": "insert",
            },
            {
                "type": "neo4j",
                "saga_id": "saga-1",
                "article_id": "art-1",
                "step_name": "neo4j_entity",
                "operation": "entity_create",
                "entity_ids": [],
                "relationship_ids": [],
            },
        ]

        execution_order = []

        async def mock_execute_cmd(cmd_self):
            execution_order.append(cmd_self.step_name)

        with patch("core.saga.executor.deserialize_compensation") as mock_deserialize:
            from core.saga.compensation import Neo4jCompensation, PostgresCompensation

            cmd1 = PostgresCompensation(
                saga_id="saga-1",
                article_id="art-1",
                step_name="pg_insert",
                operation="insert",
            )
            cmd2 = Neo4jCompensation(
                saga_id="saga-1",
                article_id="art-1",
                step_name="neo4j_entity",
                operation="entity_create",
            )
            # deserialize is called in reverse order, so neo4j first, then postgres
            mock_deserialize.side_effect = [cmd2, cmd1]

            with (
                patch.object(PostgresCompensation, "execute", new_callable=AsyncMock) as mock_pg,
                patch.object(Neo4jCompensation, "execute", new_callable=AsyncMock) as mock_neo4j,
            ):
                result = await executor.execute_compensations(comp_data_list)

        assert result.success is True
        assert len(result.completed_steps) == 2
        # neo4j_entity should be compensated first (reverse order)
        assert result.completed_steps[0] == "neo4j_entity"
        assert result.completed_steps[1] == "pg_insert"


class TestCompensationExecutorPartialFailure:
    """Tests for partial compensation failure handling."""

    @pytest.mark.asyncio
    async def test_partial_failure_continues_remaining(self, executor):
        """When one compensation fails, remaining should still execute."""
        comp_data_list = [
            {
                "type": "postgres",
                "saga_id": "saga-1",
                "article_id": "art-1",
                "step_name": "pg_insert",
                "operation": "insert",
            },
            {
                "type": "neo4j",
                "saga_id": "saga-1",
                "article_id": "art-1",
                "step_name": "neo4j_entity",
                "operation": "entity_create",
                "entity_ids": [],
                "relationship_ids": [],
            },
        ]

        call_count = 0

        async def mock_execute(cmd_self):
            nonlocal call_count
            call_count += 1
            if cmd_self.step_name == "neo4j_entity":
                raise RuntimeError("Neo4j connection failed")

        with patch("core.saga.executor.deserialize_compensation") as mock_deserialize:
            from core.saga.compensation import Neo4jCompensation, PostgresCompensation

            cmd2 = Neo4jCompensation(
                saga_id="saga-1",
                article_id="art-1",
                step_name="neo4j_entity",
                operation="entity_create",
            )
            cmd1 = PostgresCompensation(
                saga_id="saga-1",
                article_id="art-1",
                step_name="pg_insert",
                operation="insert",
            )
            mock_deserialize.side_effect = [cmd2, cmd1]

            with (
                patch.object(Neo4jCompensation, "execute", side_effect=mock_execute),
                patch.object(PostgresCompensation, "execute", new_callable=AsyncMock),
            ):
                result = await executor.execute_compensations(comp_data_list)

        assert result.success is False
        assert len(result.failed_steps) == 1
        assert result.failed_steps[0]["step_name"] == "neo4j_entity"
        assert "pg_insert" in result.completed_steps


class TestCompensationExecutorTimeout:
    """Tests for compensation timeout handling."""

    @pytest.mark.asyncio
    async def test_compensation_timeout(self):
        executor = CompensationExecutor(timeout_seconds=0)  # Immediate timeout

        comp_data = {
            "type": "postgres",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "pg_insert",
            "operation": "insert",
        }

        async def slow_execute(cmd_self):
            await asyncio.sleep(10)  # Will timeout

        with patch("core.saga.executor.deserialize_compensation") as mock_deserialize:
            from core.saga.compensation import PostgresCompensation

            cmd = PostgresCompensation(
                saga_id="saga-1",
                article_id="art-1",
                step_name="pg_insert",
                operation="insert",
            )
            mock_deserialize.return_value = cmd

            with patch.object(PostgresCompensation, "execute", side_effect=slow_execute):
                result = await executor.execute_compensations([comp_data])

        assert result.success is False
        assert len(result.failed_steps) == 1
        assert "timed out" in result.failed_steps[0]["error"]


class TestCompensationResult:
    """Tests for CompensationResult dataclass."""

    def test_success_result(self):
        result = CompensationResult(
            success=True,
            completed_steps=["step1", "step2"],
        )
        assert result.success is True
        assert len(result.completed_steps) == 2
        assert result.failed_steps == []

    def test_failure_result(self):
        result = CompensationResult(
            success=False,
            completed_steps=["step1"],
            failed_steps=[{"step_name": "step2", "error": "failed"}],
        )
        assert result.success is False
        assert len(result.failed_steps) == 1


class TestExecuteSingleCompensation:
    """Tests for execute_single_compensation."""

    @pytest.mark.asyncio
    async def test_single_success(self, executor):
        comp_data = {
            "type": "postgres",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "pg_insert",
            "operation": "insert",
        }

        with patch("core.saga.executor.deserialize_compensation") as mock_deserialize:
            mock_cmd = AsyncMock()
            mock_deserialize.return_value = mock_cmd

            result = await executor.execute_single_compensation(comp_data)

        assert result is True

    @pytest.mark.asyncio
    async def test_single_failure(self, executor):
        comp_data = {
            "type": "postgres",
            "saga_id": "saga-1",
            "article_id": "art-1",
            "step_name": "pg_insert",
            "operation": "insert",
        }

        with patch("core.saga.executor.deserialize_compensation") as mock_deserialize:
            mock_cmd = AsyncMock()
            mock_cmd.execute.side_effect = RuntimeError("DB error")
            mock_deserialize.return_value = mock_cmd

            result = await executor.execute_single_compensation(comp_data)

        assert result is False
