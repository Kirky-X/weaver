# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Narrative synthesis pipeline node — analyzes article framing dimensions.

Generates a NarrativeNode capturing how an article frames its story across
four dimensions: source_bias, frame, tone, emphasis. The node calls the LLM
via CallPoint.NARRATIVE_SYNTHESIS, persists the result to the graph database
via GraphWriter.merge_narrative, and writes the narrative data back to
pipeline state.

Failure handling follows Rule 12 (失败显性化): LLM failures and graph_writer
failures both mark "narrative" in state["degraded_fields"] without blocking
the pipeline. The narrative data is only committed to state when both LLM
call and graph persistence succeed.

Exception handling policy (aligned with AnalyzeNode):
- AllProvidersFailedError / CircuitOpenError / ValueError: expected LLM
  failures, degrade gracefully.
- Other Exception: programming errors (AttributeError, TypeError, etc.)
  propagate to fail the pipeline loudly (Rule 12 — do not hide bugs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import NarrativeOutput
from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager
    from core.prompt.loader import PromptLoader
    from core.protocols import GraphWriter

log = get_logger(__name__)


class NarrativeGeneratorNode:
    """Pipeline node: analyze and persist article narrative framing.

    Calls the LLM to extract four framing dimensions (source_bias/frame/tone/
    emphasis) from the cleaned article body+title, then persists the result as
    a NarrativeNode linked to the article's EventNode via HAS_NARRATIVE.

    Implements:
        NarrativeGeneratorNode: Pipeline narrative synthesis node
        with LLM failure + graph persistence failure degradation.

    Args:
        llm: Unified LLM client.
        budget: Token budget manager (used for body truncation).
        prompt_loader: Prompt template loader.
        graph_writer: Graph writer for NarrativeNode persistence.
    """

    def __init__(
        self,
        llm: LLMClient,
        budget: TokenBudgetManager,
        prompt_loader: PromptLoader,
        graph_writer: GraphWriter,
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._graph_writer = graph_writer

    async def execute(self, state: PipelineState) -> PipelineState:
        """Analyze narrative framing and persist NarrativeNode.

        Uses try/finally to guarantee prompt_versions is recorded on every
        exit path (success, LLM failure, persistence failure). Aligns with
        AnalyzeNode's single-call pattern (avoid 4x duplicated calls).
        """
        try:
            return await self._execute_impl(state)
        finally:
            self._record_prompt_version(state)

    async def _execute_impl(self, state: PipelineState) -> PipelineState:
        """Internal implementation — wrapped by execute() for prompt version."""
        # Skip terminal (non-news) and merged articles — same guard as AnalyzeNode
        if state.get("terminal") or state.get("is_merged"):
            return state

        cleaned = state.get("cleaned", {})
        title = cleaned.get("title", "")
        body = cleaned.get("body", "")
        entities = state.get("entities", [])
        article_id = state.get("article_id")

        # Truncate body via budget manager (same pattern as AnalyzeNode)
        truncated_body = self._budget.truncate(body, CallPoint.NARRATIVE_SYNTHESIS)

        try:
            result: NarrativeOutput = await self._llm.call_at(
                CallPoint.NARRATIVE_SYNTHESIS,
                {
                    "title": title,
                    "body": truncated_body,
                    "entities": entities,
                    "article_id": article_id,
                    "task_id": state.get("task_id"),
                },
                output_model=NarrativeOutput,
                article_id=article_id,
                task_id=state.get("task_id"),
            )
        except (AllProvidersFailedError, CircuitOpenError, ValueError) as exc:
            # Expected LLM failures — degrade gracefully.
            # ValueError covers pydantic ValidationError (invalid LLM output
            # enum/length) and JSON parse errors.
            log.warning(
                "narrative_synthesis_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                url=getattr(state.get("raw"), "url", "unknown"),
            )
            state.setdefault("degraded_fields", []).append("narrative")
            return state

        # LLM succeeded — now persist to graph database
        if not article_id:
            # Without article_id we cannot link NarrativeNode to EventNode
            # (EventNode uses article_id as its id property). Mark as
            # degraded per Rule 12 rather than silently dropping.
            log.warning(
                "narrative_missing_article_id_degraded",
                url=getattr(state.get("raw"), "url", "unknown"),
            )
            state.setdefault("degraded_fields", []).append("narrative")
            return state

        try:
            narrative_id = await self._graph_writer.merge_narrative(
                article_id=str(article_id),
                source_bias=result.source_bias,
                frame=result.frame,
                tone=result.tone,
                emphasis=result.emphasis,
            )
        except Exception as exc:
            # Graph persistence failed — log loudly (Rule 12) but do not
            # block the pipeline. The narrative data is not committed to
            # state because it is not persisted anywhere durable.
            log.warning(
                "narrative_persist_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                article_id=str(article_id),
                url=getattr(state.get("raw"), "url", "unknown"),
            )
            state.setdefault("degraded_fields", []).append("narrative")
            return state

        state["narrative"] = {
            "source_bias": result.source_bias,
            "frame": result.frame,
            "tone": result.tone,
            "emphasis": result.emphasis,
            "narrative_id": narrative_id,
        }

        log.info(
            "narrative_synthesized",
            url=getattr(state.get("raw"), "url", "unknown"),
            article_id=str(article_id),
            frame=result.frame,
            tone=result.tone,
        )
        return state

    def _record_prompt_version(self, state: PipelineState) -> None:
        """Record the prompt template version in pipeline state.

        Wrapped in try/except to ensure prompt loader failure does not
        break the degradation path (Rule 12 — do not let observability
        code hide the primary failure).
        """
        try:
            state.setdefault("prompt_versions", {})["narrative_synthesis"] = (
                self._prompt_loader.get_version("narrative_synthesis")
            )
        except Exception as exc:
            log.warning(
                "narrative_prompt_version_record_failed",
                error=str(exc),
            )
