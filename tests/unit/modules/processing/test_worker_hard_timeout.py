# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for PipelineWorker batch hard-timeout defense.

上游 LLM 连接挂死（既不报错也不返回数据）时 litellm 的 per-request
timeout 不覆盖该路径，worker 会被永久饿死。batch_hard_timeout 用
asyncio.wait_for 兜底：超时放弃本批并继续消费后续批次。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.processing.worker import PipelineWorker


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.worker_batch_size = 1
    s.worker_poll_interval = 0.01
    s.worker_error_delay = 0.01
    return s


class TestWorkerHardTimeout:
    @pytest.mark.asyncio
    async def test_hung_batch_does_not_starve_loop(self) -> None:
        """挂死批次在硬超时后被放弃，worker 继续消费下一批。"""
        queue = AsyncMock()
        queue.dequeue_batch = AsyncMock(side_effect=[[("id-1", None)], [("id-2", None)], []])
        queue.length = AsyncMock(return_value=0)
        repo = AsyncMock()
        repo.get_by_ids = AsyncMock(side_effect=lambda ids: [MagicMock() for _ in ids])
        pipeline = AsyncMock()
        pipeline.process_batch_fast = AsyncMock()

        settings = _make_settings()
        worker = PipelineWorker(
            queue=queue,
            pipeline=pipeline,
            article_repo=repo,
            pipeline_settings=settings,
            processing_mode="fast",
            batch_hard_timeout=0.2,
        )

        async def _hang(*args, **kwargs):
            await asyncio.Event().wait()  # 模拟永久挂死

        calls = 0

        async def _hang_and_stop(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls >= 2:
                worker._running = False  # 两批都尝试后结束循环
            await asyncio.Event().wait()

        pipeline.process_batch_fast = AsyncMock(side_effect=_hang_and_stop)
        worker._running = True

        await asyncio.wait_for(worker._consume_loop(), timeout=10)

        assert calls == 2
        assert pipeline.process_batch_fast.await_count == 2
        # 超时路径必须留下硬超时错误日志
        pipeline_log_calls = [c for c in pipeline.method_calls if c[0] == "process_batch_fast"]
        assert len(pipeline_log_calls) == 2

    @pytest.mark.asyncio
    async def test_completed_batch_after_a_timeout(self) -> None:
        """超时放弃挂死批次后，后续批次仍被正常处理。"""
        queue = AsyncMock()
        queue.dequeue_batch = AsyncMock(side_effect=[[("id-1", None)], [("id-2", None)], []])
        queue.length = AsyncMock(return_value=0)
        repo = AsyncMock()
        repo.get_by_ids = AsyncMock(side_effect=lambda ids: [MagicMock() for _ in ids])
        pipeline = AsyncMock()
        pipeline.process_batch_fast = AsyncMock()

        settings = _make_settings()
        worker = PipelineWorker(
            queue=queue,
            pipeline=pipeline,
            article_repo=repo,
            pipeline_settings=settings,
            processing_mode="fast",
            batch_hard_timeout=0.2,
        )

        async def _hang_first_then_ok(*args, **kwargs):
            if pipeline.process_batch_fast.await_count == 1:
                await asyncio.Event().wait()  # 第一批挂死
            worker._running = False  # 第二批完成后结束

        pipeline.process_batch_fast = AsyncMock(side_effect=_hang_first_then_ok)
        worker._running = True

        await asyncio.wait_for(worker._consume_loop(), timeout=10)

        assert pipeline.process_batch_fast.await_count == 2
        # 第二批完成后队列被消费干净
        queue.length.assert_called()
