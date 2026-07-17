# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Schema extractor pipeline node — identifies event type and pattern.

Calls the LLM to extract the article's event_type (e.g. 融资/政策发布) and
generate a JSON Schema pattern describing the event's structural fields.
The result is persisted as a SchemaNode via GraphWriter.merge_schema.

SchemaNode is MERGEd by event_type (not by article_id), so multiple articles
reporting the same event type collapse into one SchemaNode — this is the
idempotent schema registry consumed by SchemaDrivenStructuredOutput.

Failure handling follows Rule 12 (失败显性化): LLM failures and graph_writer
failures both mark "schema" in state["degraded_fields"] without blocking
the pipeline. The schema data is only committed to state when both LLM
call and graph persistence succeed.

Exception handling policy (aligned with NarrativeGeneratorNode):
- AllProvidersFailedError / CircuitOpenError / ValueError: expected LLM
  failures, degrade gracefully.
- Other Exception: programming errors propagate to fail the pipeline loudly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.llm.resilience.circuit_breaker import CircuitOpenError
from core.llm.resilience.pool import AllProvidersFailedError
from core.llm.types import CallPoint
from core.llm.validation.output_validator import SchemaExtractorOutput
from core.observability import get_logger
from modules.processing.pipeline.state import PipelineState

if TYPE_CHECKING:
    from core.llm.client import LLMClient
    from core.llm.config.token_budget import TokenBudgetManager
    from core.prompt.loader import PromptLoader
    from core.protocols import GraphWriter

log = get_logger(__name__)


class SchemaExtractorNode:
    """Pipeline node: extract event schema and persist SchemaNode.

    Calls the LLM to identify the article's event_type and generate a JSON
    Schema pattern, then persists the result as a SchemaNode MERGEd by
    event_type (no relationships — SchemaNode is a standalone schema registry).

    Implements:
        SchemaExtractorNode: Pipeline schema extraction node
        with LLM failure + graph persistence failure degradation.

    Args:
        llm: Unified LLM client.
        budget: Token budget manager (used for body truncation).
        prompt_loader: Prompt template loader.
        graph_writer: Graph writer for SchemaNode persistence.
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
        """Extract event schema and persist SchemaNode.

        Uses try/finally to guarantee prompt_versions is recorded on every
        exit path (success, LLM failure, persistence failure). Aligns with
        NarrativeGeneratorNode's single-call pattern.
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
        truncated_body = self._budget.truncate(body, CallPoint.SCHEMA_EXTRACTION)

        try:
            result: SchemaExtractorOutput = await self._llm.call_at(
                CallPoint.SCHEMA_EXTRACTION,
                {
                    "title": title,
                    "body": truncated_body,
                    "entities": entities,
                    "article_id": article_id,
                    "task_id": state.get("task_id"),
                },
                output_model=SchemaExtractorOutput,
                article_id=article_id,
                task_id=state.get("task_id"),
            )
        except (AllProvidersFailedError, CircuitOpenError, ValueError) as exc:
            # Expected LLM failures — degrade gracefully.
            # ValueError covers pydantic ValidationError (invalid LLM output
            # length/range) and JSON parse errors.
            log.warning(
                "schema_extraction_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                url=getattr(state.get("raw"), "url", "unknown"),
            )
            state.setdefault("degraded_fields", []).append("schema")
            return state

        # LLM succeeded — now persist to graph database
        try:
            schema_id = await self._graph_writer.merge_schema(
                event_type=result.event_type,
                pattern=result.pattern,
                confidence=result.confidence,
            )
        except Exception as exc:
            # Graph persistence failed — log loudly (Rule 12) but do not
            # block the pipeline. The schema data is not committed to
            # state because it is not persisted anywhere durable.
            log.warning(
                "schema_persist_failed_degraded",
                exc_type=type(exc).__name__,
                error=str(exc),
                event_type=result.event_type,
                url=getattr(state.get("raw"), "url", "unknown"),
            )
            state.setdefault("degraded_fields", []).append("schema")
            return state

        state["schema"] = {
            "event_type": result.event_type,
            "pattern": result.pattern,
            "confidence": result.confidence,
            "schema_id": schema_id,
        }

        log.info(
            "schema_extracted",
            url=getattr(state.get("raw"), "url", "unknown"),
            article_id=str(article_id) if article_id else None,
            event_type=result.event_type,
            confidence=result.confidence,
        )
        return state

    def _record_prompt_version(self, state: PipelineState) -> None:
        """Record the prompt template version in pipeline state.

        Wrapped in try/except to ensure prompt loader failure does not
        break the degradation path (Rule 12 — do not let observability
        code hide the primary failure).
        """
        try:
            state.setdefault("prompt_versions", {})["schema_extraction"] = (
                self._prompt_loader.get_version("schema_extraction")
            )
        except Exception as exc:
            log.warning(
                "schema_prompt_version_record_failed",
                error=str(exc),
            )
