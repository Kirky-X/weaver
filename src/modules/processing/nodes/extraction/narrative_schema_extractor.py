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
    ) -> None:
        self._llm = llm
        self._budget = budget
        self._prompt_loader = prompt_loader
        self._graph_writer = graph_writer

    async def execute(self, state: PipelineState) -> PipelineState:
        """Extract narrative + schema, persist both, degrade per-write.

        Uses try/finally to guarantee prompt_versions is recorded on every
        exit path (success, LLM failure, persistence failure).
        """
        try:
            return await self._execute_impl(state)
        finally:
            self._record_prompt_version(state)

    async def _execute_impl(self, state: PipelineState) -> PipelineState:
        # Skip terminal (non-news) and merged articles — same guard as AnalyzeNode.
        if state.get("terminal") or state.get("is_merged"):
            return state

        cleaned = state.get("cleaned", {})
        title = cleaned.get("title", "")
        body = cleaned.get("body", "")
        entities = state.get("entities", [])
        article_id = state.get("article_id")
        url = getattr(state.get("raw"), "url", "unknown")

        truncated_body = self._budget.truncate(body, CallPoint.NARRATIVE_SCHEMA)

        try:
            result: NarrativeSchemaOutput = await self._llm.call_at(
                CallPoint.NARRATIVE_SCHEMA,
                {
                    "title": title,
                    "body": truncated_body,
                    "entities": entities,
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
            return state

        # --- Narrative persistence (requires article_id to link EventNode) ---
        # SchemaNode is MERGEd by event_type (no article_id), but NarrativeNode
        # must link to the article's EventNode — without article_id we cannot
        # persist narrative, so degrade it while still writing schema below.
        if not article_id:
            log.warning("narrative_missing_article_id_degraded", url=url)
            state.setdefault("degraded_fields", []).append("narrative")
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

        log.info(
            "narrative_schema_extracted",
            url=url,
            article_id=str(article_id) if article_id else None,
            event_type=result.event_type,
            frame=result.frame,
            tone=result.tone,
        )
        return state

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
