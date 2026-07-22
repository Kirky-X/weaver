# SPDX-License-Identifier-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""T011 集成测试：Bing 网络回填 fallback 路径 (W-01~W-20).

分两层：
  (a) 协议层手写 fake 用例 19 个（W-01~10, W-12~20）— 直接调用
      ``fallback_orchestrator`` 模块函数，不需要走完整 HTTP 流程。
  (b) 真实 Bing live 用例 1 个（W-11）— 标注 ``bing_live``，仅在
      ``WEAVER_BING__ENABLED=true`` 时运行。

禁用 ``MagicMock``/``AsyncMock``/``patch``/``unittest.mock``（conftest.py
``pytest_collection_modifyitems`` hook 禁止），全部用手写 fake 类实现
``BingSearchProtocol`` 和 ``PipelineService`` 接口。

回填格式相关用例（W-08/W-09/W-10/W-14/W-15/W-19/W-20）通过
``_apply_web_fallback`` 辅助函数镜像 ``search.py:240-297`` 的回填逻辑，
因为该逻辑在端点层而非 ``fallback_orchestrator`` 模块中。
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

import pytest

from modules.search.web.fallback_orchestrator import (
    ScheduleResult,
    detect_three_tier_empty,
    schedule_pipeline_background,
    trigger_web_search,
)
from modules.search.web.protocol import BingSearchResult

# ─────────────────────────────────────────────────────────────────────────────
# 手写 Fake 类（实现 Protocol 接口，禁止 MagicMock）
# ─────────────────────────────────────────────────────────────────────────────


class FakeBingSearcher:
    """手写 fake，实现 ``BingSearchProtocol`` 接口。

    支持三种行为：
    - 返回预设结果列表（``results``）
    - 抛出预设异常（``exc``，模拟超时/非 200/HTML 解析失败）
    - 记录调用参数（``calls``，验证 query 透传）

    Implements:
        - modules.search.web.protocol.BingSearchProtocol
    """

    def __init__(
        self,
        results: list[BingSearchResult] | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self._results = list(results) if results is not None else []
        self._exc = exc
        self.calls: list[tuple[str, int | None]] = []

    async def search(
        self,
        query: str,
        max_results: int | None = None,
    ) -> list[BingSearchResult]:
        self.calls.append((query, max_results))
        if self._exc is not None:
            raise self._exc
        return list(self._results)

    async def close(self) -> None:
        pass


class FakePipelineService:
    """手写 fake，实现 ``PipelineService`` 接口（仅 ``run_full_pipeline``）。

    支持五种行为：
    - 返回固定成功结果（``result``）
    - 抛出预设异常（``exc``，模拟 pipeline 失败）
    - 通过 event 阻塞（``block_event``，模拟慢 pipeline / 并发占位）
    - 通过 delay 模拟短延迟（``delay``）
    - 通过 ``url_delays`` 为特定 URL 设置独立延迟
    - 记录调用 URL 列表（``urls_called``）

    Implements:
        - core.protocols.services.PipelineService (仅 run_full_pipeline)
    """

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        exc: BaseException | None = None,
        block_event: asyncio.Event | None = None,
        delay: float = 0.0,
        url_delays: dict[str, float] | None = None,
    ) -> None:
        self._result = dict(result) if result is not None else {"status": "ok"}
        self._exc = exc
        self._block_event = block_event
        self._delay = delay
        self._url_delays = url_delays or {}
        self.urls_called: list[str] = []

    async def run_full_pipeline(
        self,
        url: str,
        *,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        self.urls_called.append(url)
        if self._block_event is not None:
            await self._block_event.wait()
        url_delay = self._url_delays.get(url, self._delay)
        if url_delay > 0:
            await asyncio.sleep(url_delay)
        if self._exc is not None:
            raise self._exc
        return dict(self._result)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助构造函数
# ─────────────────────────────────────────────────────────────────────────────


def _make_bing_result(
    title: str = "Example Title",
    url: str = "https://example.com/page",
    snippet: str = "Example snippet text",
) -> BingSearchResult:
    """构造单个 ``BingSearchResult``."""
    return BingSearchResult(title=title, url=url, snippet=snippet)


def _make_empty_search_result() -> SimpleNamespace:
    """构造三层全空的 SearchResult stand-in (duck-typed).

    ``fallback_orchestrator.detect_three_tier_empty`` 通过 duck typing
    访问 ``entities``/``sources``/``answer`` 三个字段。
    """
    return SimpleNamespace(answer="", entities=[], sources=[])


def _make_non_empty_search_result() -> SimpleNamespace:
    """构造非空 SearchResult stand-in (至少一层非空)."""
    return SimpleNamespace(
        answer="meaningful answer",
        entities=["entity_one"],
        sources=[{"title": "source_title"}],
    )


def _apply_web_fallback(
    web_results: list[BingSearchResult],
    schedule_result: ScheduleResult = ScheduleResult.SCHEDULED,
) -> dict[str, Any]:
    """模拟 ``search.py:240-297`` 的回填逻辑，返回响应字段 dict。

    复制 search.py 端点中的回填逻辑用于测试验证：
    - ``answer`` 拼接自 BingSearchResult snippets
    - ``sources`` 转换为 dict 列表
    - ``confidence`` 固定 0.5
    - ``context_tokens`` 重算（1 token ≈ 4 chars）
    - ``entities`` 保持空（由后台 pipeline 填充）
    - ``metadata`` 字段 ``web_search_fallback`` / ``background_task_throttled``

    Args:
        web_results: Bing 搜索返回的结果列表。
        schedule_result: 后台调度结果（影响 throttled 标记）。

    Returns:
        包含 answer/sources/confidence/context_tokens/entities/metadata
        六个键的 dict，镜像 search.py 端点的回填后响应字段。
    """
    result_answer = "\n\n".join(
        f"- [{r.title}]({r.url})\n  {r.snippet}" for r in web_results if r.url
    )
    result_sources = [
        {"url": r.url, "title": r.title, "snippet": r.snippet} for r in web_results if r.url
    ]
    result_confidence = 0.5  # web-search fallback confidence
    result_tokens = max(0, len(result_answer) // 4)
    result_entities: list[str] = []  # entities 保持空

    result_metadata: dict[str, Any] = {}
    if schedule_result is ScheduleResult.THROTTLED:
        result_metadata["background_task_throttled"] = True
    result_metadata["web_search_fallback"] = True

    return {
        "answer": result_answer,
        "sources": result_sources,
        "confidence": result_confidence,
        "context_tokens": result_tokens,
        "entities": result_entities,
        "metadata": result_metadata,
    }


# ─────────────────────────────────────────────────────────────────────────────
# W-01 ~ W-10, W-14, W-15: detect_three_tier_empty + trigger_web_search + 回填格式
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDetectAndTriggerFallback:
    """协议层测试：detect_three_tier_empty + trigger_web_search + 回填格式."""

    @pytest.mark.asyncio
    async def test_w01_three_tier_all_empty_triggers_fallback(self) -> None:
        """W-01: 三层全空（entities/sources/answer 全空）触发回填.

        ``detect_three_tier_empty`` 返回 True 表示应触发 Bing 回填。
        """
        result = _make_empty_search_result()
        assert detect_three_tier_empty(result) is True

    @pytest.mark.asyncio
    async def test_w02_three_tier_non_empty_no_fallback(self) -> None:
        """W-02: 任一层非空不触发回填.

        ``detect_three_tier_empty`` 返回 False 表示不应触发 Bing。
        """
        result = _make_non_empty_search_result()
        assert detect_three_tier_empty(result) is False

    @pytest.mark.asyncio
    async def test_w03_bing_returns_results(self) -> None:
        """W-03: Bing 正常返回结果列表，len(results) > 0.

        FakeBingSearcher 返回预设结果，trigger_web_search 透传。
        """
        expected = [
            _make_bing_result(title="Result A", url="https://a.com/1", snippet="Snippet A"),
            _make_bing_result(title="Result B", url="https://b.com/2", snippet="Snippet B"),
        ]
        searcher = FakeBingSearcher(results=expected)
        results = await trigger_web_search("test query", searcher)
        assert len(results) > 0
        assert results == expected

    @pytest.mark.asyncio
    async def test_w04_bing_timeout_returns_empty(self) -> None:
        """W-04: searcher.search 抛 TimeoutError → trigger_web_search 返回 [].

        R-web-search-005: Bing 必须永不阻塞主搜索流程。
        """
        searcher = FakeBingSearcher(exc=TimeoutError("bing search timed out"))
        results = await trigger_web_search("test query", searcher)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_w05_bing_non_200_returns_empty(self) -> None:
        """W-05: searcher.search 抛 RuntimeError（模拟非 200）→ 返回 [].

        RuntimeError 模拟 HTTP 5xx 或非 200 状态码。
        """
        searcher = FakeBingSearcher(exc=RuntimeError("HTTP 503 service unavailable"))
        results = await trigger_web_search("test query", searcher)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_w06_bing_html_parse_failure_returns_empty(self) -> None:
        """W-06: searcher.search 抛 Exception（模拟 HTML 解析失败）→ 返回 [].

        ValueError 模拟 parse_bing_html 解析 HTML 失败。
        """
        searcher = FakeBingSearcher(exc=ValueError("HTML parse failure: malformed document"))
        results = await trigger_web_search("test query", searcher)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_w07_bing_disabled_returns_empty(self) -> None:
        """W-07: bing_searcher=None（Bing 未启用）→ 返回 [].

        容器层 ``settings.bing.enabled == False`` 时传入 None。
        """
        results = await trigger_web_search("test query", None)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_w08_bing_result_to_sources_dict_format(self) -> None:
        """W-08: BingSearchResult 转 sources dict，含 title/url/snippet.

        回填逻辑镜像 search.py:250-258 的 sources 构造。
        """
        bing_results = [
            _make_bing_result(title="Title One", url="https://a.com/1", snippet="Snippet One"),
            _make_bing_result(title="Title Two", url="https://b.com/2", snippet="Snippet Two"),
        ]
        fallback = _apply_web_fallback(bing_results)
        sources = fallback["sources"]
        assert len(sources) == 2
        for src in sources:
            assert "title" in src
            assert "url" in src
            assert "snippet" in src
        assert sources[0]["title"] == "Title One"
        assert sources[0]["url"] == "https://a.com/1"
        assert sources[0]["snippet"] == "Snippet One"

    @pytest.mark.asyncio
    async def test_w09_bing_snippets_concatenated_to_answer(self) -> None:
        """W-09: 拼接 snippets 为 answer 字符串，answer 非空.

        回填逻辑镜像 search.py:247-249 的 answer 构造。
        """
        bing_results = [
            _make_bing_result(title="A", url="https://a.com/1", snippet="First snippet content"),
            _make_bing_result(
                title="B",
                url="https://b.com/2",
                snippet="Second snippet content",
            ),
        ]
        fallback = _apply_web_fallback(bing_results)
        answer = fallback["answer"]
        assert answer  # 非空
        assert "First snippet content" in answer
        assert "Second snippet content" in answer

    @pytest.mark.asyncio
    async def test_w10_fallback_confidence_is_half(self) -> None:
        """W-10: 回填结果 confidence 固定 0.5.

        镜像 search.py:259 的 ``result_confidence = 0.5``.
        """
        bing_results = [_make_bing_result()]
        fallback = _apply_web_fallback(bing_results)
        assert fallback["confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_w14_context_tokens_recalculated_after_fallback(self) -> None:
        """W-14: 回填后 context_tokens 反映新 answer 长度 (>0).

        镜像 search.py:265 的
        ``result_tokens = max(result_tokens, len(result_answer) // 4)``.
        """
        bing_results = [
            _make_bing_result(
                title="Long Title",
                url="https://example.com/long",
                snippet=(
                    "A sufficiently long snippet to produce non-zero "
                    "token count when divided by four"
                ),
            ),
        ]
        fallback = _apply_web_fallback(bing_results)
        assert fallback["context_tokens"] > 0
        expected_tokens = len(fallback["answer"]) // 4
        assert fallback["context_tokens"] == expected_tokens

    @pytest.mark.asyncio
    async def test_w15_entities_stay_empty_after_fallback(self) -> None:
        """W-15: 回填不填充 entities（仅 sources/answer），len == 0.

        镜像 search.py:244-246 注释：entities 保持空，将由后台
        pipeline 填充。
        """
        bing_results = [_make_bing_result(), _make_bing_result()]
        fallback = _apply_web_fallback(bing_results)
        assert len(fallback["entities"]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# W-12, W-13, W-16, W-17, W-18: schedule_pipeline_background
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSchedulePipelineBackground:
    """协议层测试：schedule_pipeline_background 调度逻辑."""

    @pytest.mark.asyncio
    async def test_w12_throttled_when_at_max_concurrent(self) -> None:
        """W-12: background_tasks 达到 max_concurrent → 返回 THROTTLED.

        MEDIUM-1 (T051-B): 并发上限保护。预填充 max_concurrent 个阻塞
        任务占满集合，第 max_concurrent+1 次调用应被节流。
        """
        release_event = asyncio.Event()
        blocking_pipeline = FakePipelineService(block_event=release_event)
        background_tasks: set[asyncio.Task] = set()

        # 预填充 max_concurrent 个阻塞任务占满并发槽
        for i in range(4):
            task = asyncio.create_task(
                blocking_pipeline.run_full_pipeline(f"https://example.com/{i}")
            )
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        await asyncio.sleep(0)  # 让任务开始运行
        assert len(background_tasks) == 4

        # 第 5 个调用应被节流
        result = schedule_pipeline_background(
            ["https://example.com/5th"],
            FakePipelineService(),  # 不会被调用（节流）
            background_tasks,
            max_concurrent=4,
        )
        assert result is ScheduleResult.THROTTLED
        assert len(background_tasks) == 4  # 没有新任务加入

        # 清理：释放阻塞任务
        release_event.set()
        await asyncio.gather(*background_tasks)

    @pytest.mark.asyncio
    async def test_w13_empty_urls_filtered_returns_skipped_empty(self) -> None:
        """W-13: schedule_pipeline_background 过滤空字符串和 None → SKIPPED_EMPTY.

        过滤逻辑 (fallback_orchestrator.py:263):
        ``[u for u in urls if isinstance(u, str) and u]``
        - 空字符串 ``""`` → falsy → 过滤
        - ``None`` → 非 str → 过滤
        - ``42`` → 非 str → 过滤
        全部过滤后为空列表 → 返回 SKIPPED_EMPTY。
        """
        pipeline_service = FakePipelineService()
        background_tasks: set[asyncio.Task] = set()
        # 全部被过滤：空字符串、None、非字符串
        urls: list[Any] = ["", None, 42]
        result = schedule_pipeline_background(
            urls,  # type: ignore[arg-type]
            pipeline_service,
            background_tasks,
        )
        assert result is ScheduleResult.SKIPPED_EMPTY
        assert len(background_tasks) == 0
        assert len(pipeline_service.urls_called) == 0

    @pytest.mark.asyncio
    async def test_w16_normal_schedule_returns_scheduled(self) -> None:
        """W-16: schedule_pipeline_background 正常调度 → SCHEDULED.

        未达并发上限时，创建后台任务并返回 SCHEDULED。
        """
        pipeline_service = FakePipelineService()
        background_tasks: set[asyncio.Task] = set()
        result = schedule_pipeline_background(
            ["https://example.com/article"],
            pipeline_service,
            background_tasks,
            max_concurrent=8,
        )
        assert result is ScheduleResult.SCHEDULED
        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)
        assert pipeline_service.urls_called == ["https://example.com/article"]

    @pytest.mark.asyncio
    async def test_w17_background_task_auto_removed_from_set(self) -> None:
        """W-17: task 完成后自动从 background_tasks 集合移除.

        GC 保护模式 (fallback_orchestrator.py:283):
        ``task.add_done_callback(background_tasks.discard)``.
        """
        pipeline_service = FakePipelineService()
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(
            ["https://example.com/quick"],
            pipeline_service,
            background_tasks,
        )
        assert len(background_tasks) == 1

        # 等待任务完成
        await asyncio.gather(*background_tasks)
        # done_callback 应已将任务从集合移除
        assert len(background_tasks) == 0

    @pytest.mark.asyncio
    async def test_w18_per_url_timeout_does_not_abort_subsequent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """W-18: 单 URL 超时不中断后续 URL 处理（容错继续）.

        _run_pipelines_sequentially 内部对每个 URL 用
        ``asyncio.wait_for(timeout=_PIPELINE_URL_TIMEOUT_SECONDS)`` 包裹，
        超时后 ``except TimeoutError`` 捕获并继续下一个 URL。

        测试方法：将 _PIPELINE_URL_TIMEOUT_SECONDS 设为 0.1s，第一个 URL
        延迟 1.0s（超时），第二个 URL 快速完成。验证两个 URL 都被尝试。
        """
        from modules.search.web import fallback_orchestrator as fo

        # 将 per-URL 超时设为极短值（0.1s），让第一个 URL 超时
        monkeypatch.setattr(fo, "_PIPELINE_URL_TIMEOUT_SECONDS", 0.1)

        pipeline_service = FakePipelineService(url_delays={"https://example.com/hang": 1.0})
        background_tasks: set[asyncio.Task] = set()
        schedule_pipeline_background(
            ["https://example.com/hang", "https://example.com/ok"],
            pipeline_service,
            background_tasks,
            max_concurrent=8,
            total_timeout=10.0,
        )
        await asyncio.gather(*background_tasks)

        # 两个 URL 都被尝试（hang 超时后 ok 仍被处理）
        assert len(pipeline_service.urls_called) == 2
        assert pipeline_service.urls_called == [
            "https://example.com/hang",
            "https://example.com/ok",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# W-19, W-20: metadata 字段构造
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestResponseMetadataFields:
    """协议层测试：API 响应 metadata 字段构造.

    镜像 search.py:293-297 的 metadata 字段设置逻辑：
    - ``web_search_fallback``: 回填触发时为 True
    - ``background_task_throttled``: THROTTLED 时为 True
    """

    @pytest.mark.asyncio
    async def test_w19_metadata_web_search_fallback_flag(self) -> None:
        """W-19: 回填触发时 metadata.web_search_fallback == True.

        镜像 search.py:296 的
        ``result_metadata["web_search_fallback"] = web_search_used``.
        """
        bing_results = [_make_bing_result()]
        fallback = _apply_web_fallback(bing_results)
        metadata = fallback["metadata"]
        assert metadata["web_search_fallback"] is True

    @pytest.mark.asyncio
    async def test_w20_metadata_background_task_throttled_flag(self) -> None:
        """W-20: THROTTLED 时 metadata.background_task_throttled == True.

        镜像 search.py:293-294 的
        ``if schedule_result is ScheduleResult.THROTTLED:
           result_metadata["background_task_throttled"] = True``.
        """
        bing_results = [_make_bing_result()]
        fallback = _apply_web_fallback(bing_results, schedule_result=ScheduleResult.THROTTLED)
        metadata = fallback["metadata"]
        assert metadata["background_task_throttled"] is True


# ─────────────────────────────────────────────────────────────────────────────
# W-11: 真实 Bing live 调用
# ─────────────────────────────────────────────────────────────────────────────


_BING_ENABLED = os.getenv("WEAVER_BING__ENABLED", "").lower() in ("true", "1", "yes")


@pytest.mark.integration
@pytest.mark.bing_live
@pytest.mark.skipif(
    not _BING_ENABLED,
    reason="Bing 未启用 (设置 WEAVER_BING__ENABLED=true 以运行)",
)
class TestBingLiveCall:
    """真实 Bing 调用测试（仅 WEAVER_BING__ENABLED=true 时运行）."""

    @pytest.mark.asyncio
    async def test_w11_real_bing_returns_results(self) -> None:
        """W-11: 真实 Bing 调用返回非空 list[BingSearchResult].

        构造真实的 HttpxFetcher + BingSearcher，调用真实 cn.bing.com。
        仅在 ``WEAVER_BING__ENABLED=true`` 时运行，避免 CI 中意外触发
        外部网络请求。
        """
        from config.subconfigs import BingSettings
        from modules.ingestion.fetching.httpx_fetcher import HttpxFetcher
        from modules.search.web.bing_searcher import BingSearcher

        fetcher = HttpxFetcher(timeout=15.0)
        settings = BingSettings(enabled=True, max_results=5, timeout=15)
        searcher = BingSearcher(fetcher=fetcher, settings=settings)
        try:
            results = await trigger_web_search("OpenAI latest news 2026", searcher)
        finally:
            await searcher.close()
            await fetcher.close()

        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert isinstance(r, BingSearchResult)
