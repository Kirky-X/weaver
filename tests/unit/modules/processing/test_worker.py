# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for modules.processing.worker module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.processing.worker import PipelineWorker


@pytest.fixture
def mock_queue():
    q = AsyncMock()
    q.dequeue_batch = AsyncMock(return_value=[])
    q.length = AsyncMock(return_value=0)
    return q


@pytest.fixture
def mock_pipeline():
    p = AsyncMock()
    p.process_batch = AsyncMock()
    return p


@pytest.fixture
def mock_article_repo():
    r = AsyncMock()
    r.get_by_ids = AsyncMock(return_value=[])
    return r


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.worker_batch_size = 10
    s.worker_poll_interval = 0.01
    s.worker_error_delay = 0.01
    return s


@pytest.fixture
def worker(mock_queue, mock_pipeline, mock_article_repo, mock_settings):
    return PipelineWorker(
        queue=mock_queue,
        pipeline=mock_pipeline,
        article_repo=mock_article_repo,
        pipeline_settings=mock_settings,
    )


class TestPipelineWorkerInit:
    def test_init(self, mock_queue, mock_pipeline, mock_article_repo, mock_settings):
        w = PipelineWorker(mock_queue, mock_pipeline, mock_article_repo, mock_settings)
        assert w._queue is mock_queue
        assert w._pipeline is mock_pipeline
        assert w._article_repo is mock_article_repo
        assert w._settings is mock_settings
        assert w._running is False
        assert w._task is None


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start(self, worker):
        await worker.start()
        assert worker._running is True
        assert worker._task is not None
        # Clean up
        worker._running = False
        worker._task.cancel()
        try:
            await worker._task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop(self, worker):
        await worker.start()
        await worker.stop()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_stop_without_start(self, worker):
        await worker.stop()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, worker):
        await worker.start()
        task = worker._task
        await worker.stop()
        assert task.cancelled() or task.done()


class TestConsumeLoop:
    @pytest.mark.asyncio
    async def test_consume_empty_queue_sleeps(self, worker, mock_queue):
        mock_queue.dequeue_batch.return_value = []
        worker._running = True

        # Let it run briefly then stop
        async def stop_after_delay():
            await asyncio.sleep(0.05)
            worker._running = False

        asyncio.create_task(stop_after_delay())  # noqa: RUF006
        await worker._consume_loop()
        mock_queue.dequeue_batch.assert_called()

    @pytest.mark.asyncio
    async def test_consume_processes_items(
        self, worker, mock_queue, mock_pipeline, mock_article_repo
    ):
        article = MagicMock()
        mock_article_repo.get_by_ids.return_value = [article]

        processed = False

        async def stop_after_process():
            nonlocal processed
            # Wait for process_batch to be called
            for _ in range(50):
                if mock_pipeline.process_batch.called:
                    processed = True
                    break
                await asyncio.sleep(0.01)
            worker._running = False
            # Return empty batch so the loop can exit
            mock_queue.dequeue_batch.return_value = []

        # First call returns items, subsequent calls return empty
        mock_queue.dequeue_batch.side_effect = [
            [("article-id-1", "task-1")],
        ]
        # After the first call, return empty
        mock_queue.dequeue_batch.side_effect = None
        mock_queue.dequeue_batch.return_value = [("article-id-1", "task-1")]

        call_count = 0
        original_dequeue = mock_queue.dequeue_batch

        async def dequeue_side_effect(batch_size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [("article-id-1", "task-1")]
            return []

        mock_queue.dequeue_batch.side_effect = dequeue_side_effect

        worker._running = True
        asyncio.create_task(stop_after_process())  # noqa: RUF006
        await worker._consume_loop()
        mock_pipeline.process_batch.assert_called()

    @pytest.mark.asyncio
    async def test_consume_articles_not_found(self, worker, mock_queue, mock_article_repo):
        mock_article_repo.get_by_ids.return_value = []

        call_count = 0

        async def dequeue_side_effect(batch_size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [("missing-id", None)]
            return []

        mock_queue.dequeue_batch.side_effect = dequeue_side_effect

        worker._running = True

        async def stop_after_delay():
            await asyncio.sleep(0.1)
            worker._running = False

        asyncio.create_task(stop_after_delay())  # noqa: RUF006
        await worker._consume_loop()
        # Should not crash, just skip

    @pytest.mark.asyncio
    async def test_consume_handles_exception(self, worker, mock_queue, mock_pipeline):
        mock_pipeline.process_batch.side_effect = RuntimeError("Processing failed")
        mock_queue.dequeue_batch.return_value = [("id1", None)]
        mock_article_repo_item = MagicMock()
        worker._article_repo.get_by_ids.return_value = [mock_article_repo_item]

        worker._running = True

        async def stop_after_delay():
            await asyncio.sleep(0.1)
            worker._running = False

        asyncio.create_task(stop_after_delay())  # noqa: RUF006
        await worker._consume_loop()
        # Should not crash, error is caught


class TestDrain:
    @pytest.mark.asyncio
    async def test_drain_empty_queue(self, worker, mock_queue):
        mock_queue.dequeue_batch.return_value = []
        await worker.drain()
        mock_queue.dequeue_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_drain_processes_remaining(
        self, worker, mock_queue, mock_pipeline, mock_article_repo
    ):
        article = MagicMock()
        mock_article_repo.get_by_ids.return_value = [article]

        # First call returns items, second returns empty
        mock_queue.dequeue_batch.side_effect = [
            [("id1", "t1")],
            [],
        ]

        await worker.drain()
        mock_pipeline.process_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_drain_skips_when_no_articles(self, worker, mock_queue, mock_article_repo):
        mock_article_repo.get_by_ids.return_value = []
        mock_queue.dequeue_batch.side_effect = [
            [("id1", None)],
            [],
        ]

        await worker.drain()
        # Should not crash even when articles not found
