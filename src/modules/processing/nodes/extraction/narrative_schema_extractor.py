# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Narrative+schema extractor pipeline node (token optimization).

Merges the former NarrativeGeneratorNode and SchemaExtractorNode into a
single LLM call. Both consumed identical input (title + body + entities)
and ran concurrently in Phase 3, so collapsing them saves one LLM call
per article (~8000 input tokens) with no latency cost.

One ``call_at(NARRATIVE_SCHEMA)`` yields 7 fields (4 framing dimensions +
3 schema fields). The node splits the result into two independent graph
writes: ``GraphWriter.merge_narrative`` (NarrativeNode) and
``GraphWriter.merge_schema`` (SchemaNode). Each write degrades
independently per Rule 12 — a narrative write failure does not block the
schema write, and vice versa.

Merged mode (``merge_analyze_narrative`` in pipeline.toml): AnalyzeNode
performs a single ``call_at(ANALYZE_NARRATIVE)`` covering analyze +
narrative and stages the narrative half in ``state``, so this node
degenerates to a pure persistence step and issues no LLM call. Payload
``entities`` was removed from the standalone call — the prompt template
never consumed it, and it polluted both the cache key and input tokens.

Exception handling policy (aligned with the merged predecessors):
- AllProvidersFailedError / CircuitOpenError / ValueError: expected LLM
  failures, degrade gracefully (mark both narrative + schema).
- Other Exception: programming errors propagate to fail the pipeline loudly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import NarrativeSchemaOutput
from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager
    from core.prompt.loader import PromptLoader
    from core.protocols import GraphWriter

log = get_logger(__name__)


class NarrativeSchemaExtractorNode:
    """Pipeline node: extract narrative framing + event schema in one LLM call.

    Replaces NarrativeGeneratorNode + SchemaExtractorNode. Calls the LLM once
    via ``CallPoint.NARRATIVE_SCHEMA`` to obtain 4 framing dimensions plus an
    event schema, then persists NarrativeNode (merge_narrative) and SchemaNode
    (merge_schema) independently.

    Implements:
        NarrativeSchemaExtractorNode: Pipeline extraction node with
        independent LLM failure + per-write graph persistence degradation.

    Args:
        llm: Unified LLM client.
        budget: Token budget manager (body truncation).
        prompt_loader: Prompt template loader.
        graph_writer: Graph writer for NarrativeNode/SchemaNode persistence.
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        graph_writer: GraphWriter,
        merge_narrative: bool = False,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._graph_writer = graph_writer
        # 与 AnalyzeNode 的合并开关同源（pipeline.toml [phase3]
        # merge_analyze_narrative）。开启时本节点的 LLM 调用职责完全移交
        # analyze 合并调用：payload 缺失意味着 analyze 侧已失败并标记
        # degraded_fields——此时不回落自有调用（拆分重试会抵消合并收益，
        # 且破坏方案 A 的失败相关性语义）。
        self._merge_narrative = merge_narrative

    async def execute(self, state: PipelineState) -> PipelineState:
        """Extract narrative + schema, persist both, degrade per-write.

        Uses try/finally to guarantee prompt_versions is recorded on every
        exit path (success, LLM failure, persistence failure). Merged mode
        (payload staged by AnalyzeNode) skips the record — the consumed
        prompt is analyze_narrative, recorded by AnalyzeNode.
        """
        merged_mode = "_narrative_schema_payload" in state
        try:
            return await self._execute_impl(state)
        finally:
            if not merged_mode:
                self._record_prompt_version(state)

    async def _execute_impl(self, state: PipelineState) -> PipelineState:
        # Skip terminal (non-news) and merged articles — same guard as AnalyzeNode.
        if state.get("terminal") or state.get("is_merged"):
            return state

        url = getattr(state.get("raw"), "url", "unknown")

        # 合并模式（pipeline.toml [phase3] merge_analyze_narrative=true）：
        # AnalyzeNode 已通过 ANALYZE_NARRATIVE 调用点取得 narrative 结果并
        # 暂存 state——本节点退化为纯持久化，不再产生 chat 调用。
        merged_payload = state.pop("_narrative_schema_payload", None)
        if merged_payload is not None:
            await self._persist_all(state, merged_payload, url)
            return state

        if self._merge_narrative:
            # 合并开启但 analyze 侧未产出 payload → analyze 已失败并把
            # narrative/schema 记入 degraded_fields。此处跳过（不回落
            # 自有 LLM 调用），与 degraded 标记语义保持一致。
            log.warning(
                "narrative_merged_payload_missing_skipped",
                url=url,
            )
            return state

        # 合并开关关闭 → 自有 LLM 调用兜底路径。
        # `or {}` (not .get(key, {})): cleaned may be explicitly None, and
        # dict.get's default only applies when the key is absent.
        cleaned = state.get("cleaned") or {}
        title = cleaned.get("title", "")
        body = cleaned.get("body", "")
        article_id = state.get("article_id")

        truncated_body = self._budget.truncate(body, CallPoint.NARRATIVE_SCHEMA)

        try:
            result: NarrativeSchemaOutput = await self._llm.call_at(
                CallPoint.NARRATIVE_SCHEMA,
                {
                    "title": title,
                    "body": truncated_body,
                    "article_id": article_id,
                    "task_id": state.get("task_id"),
                },
                output_model=NarrativeSchemaOutput,
                article_id=article_id,
                task_id=state.get("task_id"),
            )
        except (AllProvidersFailedError, CircuitOpenError, ValueError) as exc:
            # Expected LLM failures — degrade both outputs gracefully.
            # ValueError covers pydantic ValidationError (invalid LLM output
            # enum/length/pattern) and JSON parse errors.
            log.warning(
                "narrative_schema_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                url=url,
            )
            state.setdefault("degraded_fields", []).extend(["narrative", "schema"])
            state.setdefault("degradation_reasons", {}).update(
                {
                    "narrative": f"LLM narrative/schema extraction failed: {exc!s}",
                    "schema": f"LLM narrative/schema extraction failed: {exc!s}",
                }
            )
            return state

        await self._persist_all(state, result, url)
        return state

    async def _persist_all(
        self,
        state: PipelineState,
        result: NarrativeSchemaOutput,
        url: str,
    ) -> None:
        """Persist narrative + schema graph writes, degrading independently.

        NarrativeNode 需要关联文章 EventNode（article_id 缺失时降级）；
        SchemaNode 按 event_type MERGE，无需 article_id。任一写失败只
        记降级，不阻断另一写（Rule 12）。
        """
        article_id = state.get("article_id")

        # --- Narrative persistence (requires article_id to link EventNode) ---
        # SchemaNode is MERGEd by event_type (no article_id), but NarrativeNode
        # must link to the article's EventNode — without article_id we cannot
        # persist narrative, so degrade it while still writing schema below.
        if not article_id:
            log.warning("narrative_missing_article_id_degraded", url=url)
            state.setdefault("degraded_fields", []).append("narrative")
            state.setdefault("degradation_reasons", {})["narrative"] = (
                "article_id missing — EventNode link impossible"
            )
        else:
            try:
                narrative_id = await self._graph_writer.merge_narrative(
                    article_id=str(article_id),
                    source_bias=result.source_bias,
                    frame=result.frame,
                    tone=result.tone,
                    emphasis=result.emphasis,
                )
                state["narrative"] = {
                    "source_bias": result.source_bias,
                    "frame": result.frame,
                    "tone": result.tone,
                    "emphasis": result.emphasis,
                    "narrative_id": narrative_id,
                }
            except Exception as exc:
                # Narrative write failed — log loudly (Rule 12) but do not
                # block the schema write below.
                log.warning(
                    "narrative_persist_failed_degraded",
                    exc_type=type(exc).__name__,
                    error=str(exc),
                    article_id=str(article_id),
                    url=url,
                )
                state.setdefault("degraded_fields", []).append("narrative")
                state.setdefault("degradation_reasons", {})["narrative"] = (
                    f"narrative persist failed: {exc!s}"
                )

        # --- Schema persistence (MERGEd by event_type, no article_id needed) ---
        try:
            schema_id = await self._graph_writer.merge_schema(
                event_type=result.event_type,
                pattern=result.pattern,
                confidence=result.confidence,
            )
            state["schema"] = {
                "event_type": result.event_type,
                "pattern": result.pattern,
                "confidence": result.confidence,
                "schema_id": schema_id,
            }
        except Exception as exc:
            # Schema write failed — log loudly (Rule 12) but do not block.
            # Narrative (if persisted above) remains in state.
            log.warning(
                "schema_persist_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                event_type=result.event_type,
                url=url,
            )
            state.setdefault("degraded_fields", []).append("schema")
            state.setdefault("degradation_reasons", {})["schema"] = (
                f"schema persist failed: {exc!s}"
            )

        log.info(
            "narrative_schema_extracted",
            url=url,
            article_id=str(article_id) if article_id else None,
            event_type=result.event_type,
            frame=result.frame,
            tone=result.tone,
        )

    def _record_prompt_version(self, state: PipelineState) -> None:
        """Record the prompt template version in pipeline state.

        Wrapped in try/except so prompt loader failure does not break the
        degradation path (Rule 12 — observability must not hide primary failure).
        """
        try:
            state.setdefault("prompt_versions", {})["narrative_schema"] = (
                self._prompt_loader.get_version("narrative_schema")
            )
        except Exception as exc:
            log.warning(
                "narrative_schema_prompt_version_record_failed",
                error=str(exc),
            )
