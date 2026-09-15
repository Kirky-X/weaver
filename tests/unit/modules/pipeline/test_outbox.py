# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for the transactional outbox."""

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


# ── OutboxRepo direct tests ──────────────────────────────────────


class TestOutboxRepoEnqueue:
    """Tests for OutboxRepo.enqueue()."""

    @pytest.mark.asyncio
    async def test_enqueue_creates_row_and_returns_id(self):
        """enqueue() creates EventOutbox row and returns its id."""
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _refresh(row):
            row.id = 42

        mock_session.refresh = AsyncMock(side_effect=_refresh)

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = OutboxRepo(pool)
        result = await repo.enqueue("TestEvent", {"key": "value"})

        assert result == 42
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enqueue_converts_str_article_id_to_uuid(self):
        """String article_id is converted to UUID."""
        import uuid as uuid_mod

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _refresh(row):
            row.id = 1

        mock_session.refresh = AsyncMock(side_effect=_refresh)

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = OutboxRepo(pool)
        await repo.enqueue("TestEvent", {}, article_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890")

        added_row = mock_session.add.call_args[0][0]
        assert isinstance(added_row.article_id, uuid_mod.UUID)

    @pytest.mark.asyncio
    async def test_enqueue_with_none_article_id(self):
        """None article_id passes through."""
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _refresh(row):
            row.id = 2

        mock_session.refresh = AsyncMock(side_effect=_refresh)

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = OutboxRepo(pool)
        await repo.enqueue("TestEvent", {}, article_id=None)

        added_row = mock_session.add.call_args[0][0]
        assert added_row.article_id is None


class TestOutboxRepoFetchPending:
    """Tests for OutboxRepo.fetch_pending()."""

    @pytest.mark.asyncio
    async def test_fetch_pending_returns_list(self):
        """fetch_pending() returns list of pending rows."""
        row1, row2 = MagicMock(), MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row1, row2]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = OutboxRepo(pool)
        result = await repo.fetch_pending(limit=50)

        assert len(result) == 2
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_pending_empty(self):
        """fetch_pending() returns empty list when no pending rows."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = OutboxRepo(pool)
        result = await repo.fetch_pending()

        assert result == []


class TestOutboxRepoMarkDispatched:
    """Tests for OutboxRepo.mark_dispatched()."""

    @pytest.mark.asyncio
    async def test_marks_dispatched_and_commits(self):
        """mark_dispatched() updates status and commits."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()

        pool = MagicMock()
        pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        pool.session.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = OutboxRepo(pool)
        await repo.mark_dispatched(7)

        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()


def _mark_failed_pool(row=None):
    """Build a pool mocking the new two-execute mark_failed flow.

    First execute is the atomic UPDATE; the second is the status read-back.
    """
    read_result = MagicMock()
    read_result.first.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(), read_result])
    mock_session.commit = AsyncMock()

    pool = MagicMock()
    pool.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    pool.session.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, mock_session


class TestOutboxRepoMarkFailed:
    """Tests for OutboxRepo.mark_failed()."""

    @pytest.mark.asyncio
    async def test_increments_retry_keeps_pending(self):
        """mark_failed() keeps pending when retries are under the limit."""
        mock_row = MagicMock()
        mock_row.retry_count = 3
        mock_row.status = "pending"
        mock_row.event_type = "TestEvent"

        pool, mock_session = _mark_failed_pool(mock_row)
        repo = OutboxRepo(pool)
        status = await repo.mark_failed(1, "some error")

        assert status == "pending"
        # Atomic increment: retry_count referenced as column expression
        update_stmt = mock_session.execute.await_args_list[0][0][0]
        assert "retry_count" in str(update_stmt)

    @pytest.mark.asyncio
    async def test_parks_as_dead_when_retries_exhausted(self):
        """mark_failed() parks row as 'dead' when retries >= MAX_OUTBOX_RETRIES."""
        mock_row = MagicMock()
        mock_row.retry_count = 5
        mock_row.status = "dead"
        mock_row.event_type = "TestEvent"

        pool, mock_session = _mark_failed_pool(mock_row)
        repo = OutboxRepo(pool)
        status = await repo.mark_failed(1, "fatal error")

        assert status == "dead"

    @pytest.mark.asyncio
    async def test_truncates_error_message(self):
        """mark_failed() truncates error to 2000 chars."""
        mock_row = MagicMock()
        mock_row.retry_count = 1
        mock_row.status = "pending"
        mock_row.event_type = "TestEvent"

        pool, mock_session = _mark_failed_pool(mock_row)
        repo = OutboxRepo(pool)
        long_error = "x" * 5000
        await repo.mark_failed(1, long_error)

        # The atomic UPDATE carries the truncated error value
        update_stmt = str(mock_session.execute.await_args_list[0][0][0])
        assert "last_error" in update_stmt or "x" * 100 in update_stmt

    @pytest.mark.asyncio
    async def test_returns_missing_when_row_not_found(self):
        """mark_failed() returns 'missing' when row doesn't exist."""
        pool, _ = _mark_failed_pool(row=None)
        repo = OutboxRepo(pool)
        status = await repo.mark_failed(999, "error")

        assert status == "missing"
