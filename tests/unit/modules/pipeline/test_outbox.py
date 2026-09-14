# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for the transactional outbox (T018)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.processing.pipeline.memory_publisher import MemoryEventPublisher
from modules.processing.pipeline.state import PipelineState
from modules.storage.postgres.outbox_repo import MAX_OUTBOX_RETRIES, OutboxRepo


def _state(article_id: str = "a-1") -> PipelineState:
    state = PipelineState(raw=MagicMock(title="T", body="B"))
    state["article_id"] = article_id
    return state


def _outbox_repo():
    repo = MagicMock()
    repo.enqueue = AsyncMock(side_effect=lambda **kw: 1)
    repo.mark_dispatched = AsyncMock()
    repo.mark_failed = AsyncMock(return_value="pending")
    repo.fetch_pending = AsyncMock(return_value=[])
    return repo


class TestMemoryEventPublisherOutbox:
    @pytest.mark.asyncio
    async def test_enqueue_before_dispatch_and_mark_dispatched(self):
        outbox = _outbox_repo()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        publisher = MemoryEventPublisher(event_bus=event_bus, outbox_repo=outbox)
        await publisher.publish([_state()])

        outbox.enqueue.assert_awaited_once()
        assert outbox.enqueue.await_args.kwargs["event_type"] == "MemoryIngestEvent"
        event_bus.publish.assert_awaited_once()
        outbox.mark_dispatched.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_failure_keeps_row_pending(self):
        outbox = _outbox_repo()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))

        publisher = MemoryEventPublisher(event_bus=event_bus, outbox_repo=outbox)
        await publisher.publish([_state()])

        outbox.mark_dispatched.assert_not_awaited()
        # row stays pending; dispatcher job retries it later

    @pytest.mark.asyncio
    async def test_without_outbox_repo_behaves_fire_and_forget(self):
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        publisher = MemoryEventPublisher(event_bus=event_bus)
        await publisher.publish([_state()])

        event_bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enqueue_failure_does_not_block_dispatch(self):
        outbox = _outbox_repo()
        outbox.enqueue = AsyncMock(side_effect=RuntimeError("pg down"))
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        publisher = MemoryEventPublisher(event_bus=event_bus, outbox_repo=outbox)
        await publisher.publish([_state()])

        # event still dispatched in-process; no crash
        event_bus.publish.assert_awaited_once()
        outbox.mark_dispatched.assert_not_awaited()


class TestOutboxDispatcherJob:
    @pytest.mark.asyncio
    async def test_dispatch_marks_rows(self):
        from modules.scheduler.consistency_jobs import ConsistencyJobs

        row = MagicMock()
        row.id = 7
        row.payload = {"article_id": "a-1", "state": {}}
        outbox = MagicMock()
        outbox.fetch_pending = AsyncMock(return_value=[row])
        outbox.mark_dispatched = AsyncMock()
        outbox.mark_failed = AsyncMock()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        jobs = ConsistencyJobs(
            relational_pool=MagicMock(),
            cache=MagicMock(),
            graph_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            outbox_repo=outbox,
            event_bus=event_bus,
        )

        count = await jobs.dispatch_outbox_events()

        assert count == 1
        outbox.mark_dispatched.assert_awaited_once_with(7)

    @pytest.mark.asyncio
    async def test_failed_dispatch_records_failure(self):
        from modules.scheduler.consistency_jobs import ConsistencyJobs

        row = MagicMock()
        row.id = 9
        row.payload = {"article_id": "a-2", "state": {}}
        outbox = MagicMock()
        outbox.fetch_pending = AsyncMock(return_value=[row])
        outbox.mark_dispatched = AsyncMock()
        outbox.mark_failed = AsyncMock(return_value="pending")
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(side_effect=RuntimeError("handler boom"))

        jobs = ConsistencyJobs(
            relational_pool=MagicMock(),
            cache=MagicMock(),
            graph_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
            outbox_repo=outbox,
            event_bus=event_bus,
        )

        count = await jobs.dispatch_outbox_events()

        assert count == 0
        outbox.mark_failed.assert_awaited_once_with(9, "handler boom")
        outbox.mark_dispatched.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_outbox_or_bus_returns_zero(self):
        from modules.scheduler.consistency_jobs import ConsistencyJobs

        jobs = ConsistencyJobs(
            relational_pool=MagicMock(),
            cache=MagicMock(),
            graph_writer=MagicMock(),
            vector_repo=MagicMock(),
            article_repo=MagicMock(),
            pending_sync_repo=MagicMock(),
        )

        assert await jobs.dispatch_outbox_events() == 0


class TestOutboxRepoRetryPolicy:
    def test_max_retries_constant(self):
        assert MAX_OUTBOX_RETRIES == 5

    @pytest.mark.asyncio
    async def test_repo_is_construction_ready(self):
        """OutboxRepo builds against a relational pool (protocol conformance)."""
        pool = MagicMock()
        repo = OutboxRepo(pool)
        assert repo._pool is pool
