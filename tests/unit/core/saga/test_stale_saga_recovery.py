# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for stale saga recovery (T017)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.saga.orchestrator import SagaOrchestrator, SagaResult, SagaStatus


def _stale_log(saga_id: uuid.UUID):
    log = MagicMock()
    log.saga_id = saga_id
    return log


def _orchestrator(stale_logs):
    log_repo = MagicMock()
    log_repo.get_stale_started_logs = AsyncMock(return_value=stale_logs)
    orchestrator = SagaOrchestrator(log_repo=log_repo)
    orchestrator.compensate_saga = AsyncMock(
        return_value=SagaResult(saga_id=uuid.uuid4(), status=SagaStatus.COMPENSATED)
    )
    return orchestrator, log_repo


class TestRecoverStaleSagas:
    @pytest.mark.asyncio
    async def test_compensates_each_distinct_stale_saga(self) -> None:
        saga_a, saga_b = uuid.uuid4(), uuid.uuid4()
        orchestrator, log_repo = _orchestrator(
            [_stale_log(saga_a), _stale_log(saga_b)]
        )

        count = await orchestrator.recover_stale_sagas(max_age_minutes=30)

        assert count == 2
        assert log_repo.get_stale_started_logs.await_count == 1
        cutoff = log_repo.get_stale_started_logs.await_args.args[0]
        assert cutoff <= datetime.now(UTC)
        assert orchestrator.compensate_saga.await_count == 2

    @pytest.mark.asyncio
    async def test_deduplicates_same_saga(self) -> None:
        saga_a = uuid.uuid4()
        orchestrator, log_repo = _orchestrator(
            [_stale_log(saga_a), _stale_log(saga_a)]
        )

        count = await orchestrator.recover_stale_sagas()

        assert count == 1
        assert orchestrator.compensate_saga.await_count == 1

    @pytest.mark.asyncio
    async def test_no_stale_logs_returns_zero(self) -> None:
        orchestrator, _log_repo = _orchestrator([])

        assert await orchestrator.recover_stale_sagas() == 0
        orchestrator.compensate_saga.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compensation_failure_continues_with_next(self) -> None:
        saga_a, saga_b = uuid.uuid4(), uuid.uuid4()
        orchestrator, log_repo = _orchestrator(
            [_stale_log(saga_a), _stale_log(saga_b)]
        )
        orchestrator.compensate_saga = AsyncMock(
            side_effect=[RuntimeError("boom"), SagaResult(saga_id=saga_b, status=SagaStatus.COMPENSATED)]
        )

        count = await orchestrator.recover_stale_sagas()

        assert count == 1
        assert orchestrator.compensate_saga.await_count == 2


class TestConsistencyJobsRecoverDelegation:
    @pytest.mark.asyncio
    async def test_returns_zero_without_orchestrator(self) -> None:
        from modules.scheduler.consistency_jobs import ConsistencyJobs

        jobs = ConsistencyJobs(
            relational_pool=MagicMock(),
            cache=MagicMock(),
            graph_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

        assert await jobs.recover_stale_sagas() == 0

    @pytest.mark.asyncio
    async def test_delegates_to_orchestrator(self) -> None:
        from modules.scheduler.consistency_jobs import ConsistencyJobs

        orchestrator = MagicMock()
        orchestrator.recover_stale_sagas = AsyncMock(return_value=3)
        jobs = ConsistencyJobs(
            relational_pool=MagicMock(),
            cache=MagicMock(),
            graph_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            saga_orchestrator=orchestrator,
        )

        assert await jobs.recover_stale_sagas() == 3
        orchestrator.recover_stale_sagas.assert_awaited_once()
