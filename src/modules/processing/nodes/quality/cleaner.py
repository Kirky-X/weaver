# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Cleaner pipeline node — trafilatura primary, LLM fallback for article content cleaning."""

from __future__ import annotations

from difflib import SequenceMatcher

import trafilatura

from core.llm.client import LLMClient
from core.llm.config.token_budget import TokenBudgetManager
from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import CleanerOutput
from core.observability import get_logger
from core.observability.metrics import metrics
from core.prompt.loader import PromptLoader
from modules.processing.pipeline.state import PipelineState

log = get_logger(__name__)

# Cleaner 节点最大重试次数 (包含首次调用)
_MAX_CLEANER_ATTEMPTS = 2


def _title_similarity(title_a: str, title_b: str) -> float:
    """Compute similarity ratio between two titles."""
    if not title_a or not title_b:
        return 0.0
    return SequenceMatcher(None, title_a.lower(), title_b.lower()).ratio()


class CleanerNode:
    """Pipeline node: clean article content via trafilatura (primary) or LLM (fallback).

    Implements: CleanerNode with trafilatura primary path.

    Strategy:
    1. If raw HTML is available, try trafilatura.extract() first.
    2. Quality check: body length >= cleaner_min_body_chars AND
       title similarity >= cleaner_min_title_similarity.
    3. If trafilatura output passes quality check, use it directly (no LLM call).
    4. Otherwise, fall back to LLM-based cleaning.
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        min_body_chars: int = 100,
        min_title_similarity: float = 0.7,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._min_body_chars = min_body_chars
        self._min_title_similarity = min_title_similarity

    def _try_trafilatura(self, state: PipelineState) -> bool:
        """Attempt trafilatura extraction from raw HTML.

        Returns True if trafilatura succeeded and quality check passed.
        """
        raw = state["raw"]
        html_content = getattr(raw, "html", None)

        if not html_content:
            log.debug("cleaner_trafilatura_skip_no_html", url=raw.url)
            return False

        try:
            extracted = trafilatura.extract(
                html_content,
                include_comments=False,
                favor_precision=True,
            )
        except Exception as e:
            log.debug(
                "cleaner_trafilatura_extract_error",
                url=raw.url,
                error=str(e),
            )
            return False

        if not extracted:
            log.debug("cleaner_trafilatura_extract_none", url=raw.url)
            return False

        # Quality check: body length
        if len(extracted) < self._min_body_chars:
            log.debug(
                "cleaner_trafilatura_body_too_short",
                url=raw.url,
                body_len=len(extracted),
                min_chars=self._min_body_chars,
            )
            return False

        # Quality check: title similarity
        # Use trafilatura bare_extraction for metadata (title)
        try:
            bare = trafilatura.bare_extraction(
                html_content,
                include_comments=False,
                favor_precision=True,
            )
        except Exception:
            bare = None

        extracted_title = ""
        if bare and isinstance(bare, dict):
            extracted_title = bare.get("title") or ""

        if extracted_title:
            sim = _title_similarity(raw.title, extracted_title)
            if sim < self._min_title_similarity:
                log.debug(
                    "cleaner_trafilatura_title_mismatch",
                    url=raw.url,
                    original_title=raw.title[:50],
                    extracted_title=extracted_title[:50],
                    similarity=round(sim, 3),
                    min_similarity=self._min_title_similarity,
                )
                return False

        # Trafilatura succeeded — populate state
        state["cleaned"] = {
            "title": extracted_title or raw.title,
            "body": extracted,
            "publish_time": raw.publish_time,
            "source_host": raw.source_host,
        }
        if bare and isinstance(bare, dict):
            author = bare.get("author")
            if author:
                state["cleaned"]["author"] = author
            date = bare.get("date")
            if date:
                # REM-002: Backfill publish_time when raw.publish_time is None.
                # Previously wrote to dead field 'llm_publish_time' which was never read.
                if not raw.publish_time:
                    state["cleaned"]["publish_time"] = str(date)

        state["tags"] = []
        state["cleaner_entities"] = []
        state["cleaner_method"] = "trafilatura"
        metrics.cleaner_method_total.labels(method="trafilatura").inc()

        log.info(
            "cleaner_trafilatura_success",
            url=raw.url,
            body_len=len(extracted),
        )
        return True

    async def _clean_via_llm(self, state: PipelineState) -> PipelineState:
        """Clean article content via LLM (original path)."""
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
                    article_id=state.get("article_id"),
                    task_id=state.get("task_id"),
                )

                state["cleaned"] = {
                    "title": result.content.title or "",
                    "subtitle": result.content.subtitle,
                    "summary": result.content.summary,
                    "body": result.content.body or "",
                    "publish_time": raw.publish_time,
                    "source_host": raw.source_host,
                }
                if result.publish_time:
                    # REM-002: Backfill publish_time when raw.publish_time is None.
                    # Previously wrote to dead field 'llm_publish_time' which was never read.
                    if not raw.publish_time:
                        state["cleaned"]["publish_time"] = result.publish_time
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
                state["cleaner_method"] = "llm"
                metrics.cleaner_method_total.labels(method="llm").inc()
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
                state["cleaner_method"] = "llm"
                metrics.cleaner_method_total.labels(method="llm").inc()
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

        return state

    async def execute(self, state: PipelineState) -> PipelineState:
        """Clean article content — trafilatura primary, LLM fallback."""
        if state.get("terminal"):
            return state

        # Try trafilatura first
        if self._try_trafilatura(state):
            state.setdefault("prompt_versions", {})["cleaner"] = self._prompt_loader.get_version(
                "cleaner"
            )
            log.info(
                "cleaned",
                url=state["raw"].url,
                tags_count=len(state.get("tags", [])),
                method="trafilatura",
            )
            return state

        # Fallback to LLM
        state = await self._clean_via_llm(state)
        state.setdefault("prompt_versions", {})["cleaner"] = self._prompt_loader.get_version(
            "cleaner"
        )
        log.info(
            "cleaned",
            url=state["raw"].url,
            tags_count=len(state.get("tags", [])),
            method="llm",
        )
        return state
