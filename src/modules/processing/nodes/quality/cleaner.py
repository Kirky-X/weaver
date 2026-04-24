# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Cleaner pipeline node — LLM-based article content cleaning."""

from __future__ import annotations

from core.llm.client import LLMClient
from core.llm.config.token_budget import TokenBudgetManager
from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import CleanerOutput
from core.observability.logging import get_logger
from core.prompt.loader import PromptLoader
from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)

# Cleaner 节点最大重试次数 (包含首次调用)
_MAX_CLEANER_ATTEMPTS = 2


class CleanerNode:
    """Pipeline node: clean article content via LLM."""

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader

    async def execute(self, state: PipelineState) -> PipelineState:
        """Clean article content."""
        if state.get("terminal"):
            return state

        raw = state["raw"]
        body_trunc = self._budget.truncate(raw.body, CallPoint.CLEANER)

        payload = {
            "title": raw.title,
            "body": body_trunc,
            "article_id": state.get("article_id"),
            "task_id": state.get("task_id"),
        }

        for attempt in range(_MAX_CLEANER_ATTEMPTS):
            try:
                result: CleanerOutput = await self._llm.call_at(
                    CallPoint.CLEANER,
                    payload,
                    output_model=CleanerOutput,
                )

                state["cleaned"] = {
                    "title": result.content.title,
                    "subtitle": result.content.subtitle,
                    "summary": result.content.summary,
                    "body": result.content.body,
                    "publish_time": raw.publish_time,
                    "source_host": raw.source_host,
                }
                if result.publish_time:
                    state["cleaned"]["llm_publish_time"] = result.publish_time
                if result.author:
                    state["cleaned"]["author"] = result.author
                state["tags"] = result.tags
                state["cleaner_entities"] = [
                    {
                        "name": e.name,
                        "type": e.type,
                        "description": e.description,
                    }
                    for e in result.entities
                ]
                # 成功则直接返回
                break

            except (
                AllProvidersFailedError,
                CircuitOpenError,
                ValueError,
                TimeoutError,
                Exception,
            ) as e:
                if attempt < _MAX_CLEANER_ATTEMPTS - 1:
                    # 构造 retry_hint 提示 LLM 修正输出
                    retry_hint = (
                        f"上一次输出解析失败: {e!s}。"
                        "请确保返回完整的 JSON 结构，包含 content 嵌套对象"
                        "（含 title、body 字段），entities 中每项必须含 name、type、description。"
                    )
                    payload = {**payload, "_retry_hint": retry_hint}
                    log.info(
                        "cleaner_retry",
                        attempt=attempt + 1,
                        exc_type=type(e).__name__,
                        error=str(e),
                        url=raw.url,
                    )
                    continue

                # 最后一次尝试也失败, 降级处理
                log.warning(
                    "cleaner_failed_using_original",
                    exc_type=type(e).__name__,
                    error=str(e),
                    url=raw.url,
                )
                state["cleaned"] = {
                    "title": raw.title,
                    "body": raw.body,
                    "publish_time": raw.publish_time,
                    "source_host": raw.source_host,
                }
                state["tags"] = []
                state["cleaner_entities"] = []
                state.setdefault("degraded_fields", []).extend(
                    ["cleaned.title", "cleaned.body", "tags", "cleaner_entities"]
                )
                state.setdefault("degradation_reasons", {}).update(
                    {
                        "cleaned.title": f"LLM cleaner failed: {e!s}",
                        "cleaned.body": f"LLM cleaner failed: {e!s}",
                        "tags": f"LLM cleaner failed: {e!s}",
                        "cleaner_entities": f"LLM cleaner failed: {e!s}",
                    }
                )

        state.setdefault("prompt_versions", {})["cleaner"] = self._prompt_loader.get_version(
            "cleaner"
        )

        log.info("cleaned", url=raw.url, tags_count=len(state.get("tags", [])))
        return state
