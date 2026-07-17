# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for PipelineWorker processing_mode wiring — D2 dead code fix.

``process_batch_fast`` exists in Pipeline but is never called by
PipelineWorker, making the fast mode dead code. This test asserts
that when ``processing_mode="fast"``, the worker dispatches to
``process_batch_fast`` instead of ``process_batch``.

See ``temp/report.md`` D2 (fast 模式死代码) and specmark change
``fix-pipeline-deadcode-perf`` T015-T016.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.processing.worker import PipelineWorker


@pytest.fixture
def mock_queue() -> AsyncMock:
    """Mock queue returning one item on first dequeue, empty after."""
    q = AsyncMock()
    item = ("article-uuid-1", "task-uuid-1")
    q.dequeue_batch = AsyncMock(side_effect=[[item], []])
    q.length = AsyncMock(return_value=0)
    return q


@pytest.fixture
def mock_pipeline() -> AsyncMock:
    """Mock pipeline with both process_batch and process_batch_fast."""
    p = AsyncMock()
    p.process_batch = AsyncMock()
    p.process_batch_fast = AsyncMock()
    return p


@pytest.fixture
def mock_article_repo() -> AsyncMock:
    """Mock article_repo returning one article."""
    r = AsyncMock()
    r.get_by_ids = AsyncMock(return_value=[MagicMock()])
    return r


@pytest.fixture
def mock_settings() -> MagicMock:
    """Mock pipeline settings."""
    s = MagicMock()
    s.worker_batch_size = 10
    s.worker_poll_interval = 0.01
    s.worker_error_delay = 0.01
    return s


class TestPipelineWorkerProcessingMode:
    """Tests for processing_mode dispatch (D2 fix)."""

    @pytest.mark.asyncio
    async def test_fast_mode_calls_process_batch_fast(
        self,
        mock_queue: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_article_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        """When processing_mode='fast', process_batch_fast must be called."""
        worker = PipelineWorker(
            queue=mock_queue,
            pipeline=mock_pipeline,
            article_repo=mock_article_repo,
            pipeline_settings=mock_settings,
            processing_mode="fast",
        )
        # _consume_loop checks self._running before entering loop body
        worker._running = True

        # Stop the loop after first process_batch_fast call
        async def _stop_after_fast(*args, **kwargs):
            worker._running = False

        mock_pipeline.process_batch_fast.side_effect = _stop_after_fast

        await worker._consume_loop()

        mock_pipeline.process_batch_fast.assert_called_once()
        mock_pipeline.process_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_deep_mode_calls_process_batch(
        self,
        mock_queue: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_article_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        """When processing_mode='deep' (default), process_batch must be called."""
        worker = PipelineWorker(
            queue=mock_queue,
            pipeline=mock_pipeline,
            article_repo=mock_article_repo,
            pipeline_settings=mock_settings,
            processing_mode="deep",
        )
        worker._running = True

        async def _stop_after_deep(*args, **kwargs):
            worker._running = False

        mock_pipeline.process_batch.side_effect = _stop_after_deep

        await worker._consume_loop()

        mock_pipeline.process_batch.assert_called_once()
        mock_pipeline.process_batch_fast.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_processing_mode_is_deep(
        self,
        mock_queue: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_article_repo: AsyncMock,
        mock_settings: MagicMock,
    ) -> None:
        """Without explicit processing_mode, default to 'deep'."""
        worker = PipelineWorker(
            queue=mock_queue,
            pipeline=mock_pipeline,
            article_repo=mock_article_repo,
            pipeline_settings=mock_settings,
        )

        assert worker._processing_mode == "deep"
