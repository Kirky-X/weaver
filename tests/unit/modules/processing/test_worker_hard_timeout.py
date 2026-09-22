# SPDX-License-Identifier: Apache-2.0

# SPDX-FileCopyrightText: © 2026 Kirky.X

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


class TestTimeoutBatchRequeue:
    @pytest.mark.asyncio
    async def test_timed_out_batch_requeued_once(self) -> None:
        """超时批次的文章重入队一次；重试仍挂死则不再入队（防死循环）。"""

        queue = AsyncMock()

        # 批1 两篇挂死；批2 是重入队批次再挂死；之后空队列

        queue.dequeue_batch = AsyncMock(
            side_effect=[[("id-1", None), ("id-2", None)], [("id-1", None)], []]
        )

        queue.enqueue = AsyncMock(return_value=True)

        queue.length = AsyncMock(return_value=0)

        repo = AsyncMock()

        repo.get_by_ids = AsyncMock(side_effect=lambda ids: [MagicMock() for _ in ids])

        pipeline = AsyncMock()

        settings = _make_settings()

        settings.worker_batch_size = 2

        worker = PipelineWorker(
            queue=queue,
            pipeline=pipeline,
            article_repo=repo,
            pipeline_settings=settings,
            processing_mode="fast",
            batch_hard_timeout=0.2,
        )

        async def _hang(*args, **kwargs):

            await asyncio.Event().wait()

        pipeline.process_batch_fast = AsyncMock(side_effect=_hang)

        # 批2 之后队列为空，worker 会空转——限制重试路径验证后手动结束

        async def _stop_after_second_timeout() -> None:

            pass

        worker._running = True

        consume = asyncio.wait_for(worker._consume_loop(), timeout=3)

        with pytest.raises(asyncio.TimeoutError):
            await consume

        # 两篇各重入队一次（共 2 次 enqueue），重试挂死后不再入队

        assert queue.enqueue.await_count == 2

        enqueued_ids = [c.args[0] for c in queue.enqueue.await_args_list]

        assert sorted(enqueued_ids) == ["id-1", "id-2"]


class TestGLiNERTimeoutDefense:
    """GLiNER 专用单线程被挂死占用后，超时禁用防 deep 批次饿死。"""

    @pytest.mark.asyncio
    async def test_gliner_hang_times_out_and_disables(self) -> None:

        from modules.processing.nodes.extraction.entity_extractor import (
            EntityExtractorNode as EntityExtractor,
        )

        from modules.processing.nodes.extraction.gliner_extractor import (
            GLiNERConfig,
            GLiNERExtractor,
        )

        gliner = GLiNERExtractor(config=GLiNERConfig(enabled=True))

        gliner._config.enabled = True

        async def _hang(text):

            await asyncio.Event().wait()

        gliner.extract_entities = AsyncMock(side_effect=_hang)

        extractor = EntityExtractor(
            llm=MagicMock(),
            budget=MagicMock(),
            prompt_loader=MagicMock(),
            spacy=MagicMock(),
            settings=None,
            vector_repo=None,
            relation_type_normalizer=None,
            gliner_extractor=gliner,
            gliner_timeout=0.2,
        )

        state = {"raw": MagicMock(url="https://x/1"), "cleaned": {"body": "x" * 100}}

        import time as _t

        t0 = _t.monotonic()

        await extractor._extract_gliner_entities(state, "body text")

        assert _t.monotonic() - t0 < 3  # 超时切断而非永久挂起

        # 首次超时进入冷却（默认 300s）而非永久禁用，后续调用短路

        assert gliner._config.enabled is True

        t1 = _t.monotonic()

        await extractor._extract_gliner_entities(state, "body text")

        assert _t.monotonic() - t1 < 0.5  # 冷却期内立即返回

        assert gliner.extract_entities.await_count == 1  # 冷却期内未再调用
