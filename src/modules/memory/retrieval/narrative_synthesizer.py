# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Narrative Synthesizer for MAGMA multi-graph memory.

Synthesizes retrieved context into coherent narratives using LLM.
Implements the NarrativeSynthesizer component from MAGMA specification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability import get_logger
from modules.memory.core.graph_types import OutputMode, SynthesisResult

if TYPE_CHECKING:
    from core.llm.client import LLMClient

log = get_logger(__name__)


class NarrativeSynthesizer:
    """Synthesizes retrieved context into narrative responses.

    Supports two output modes:
    - CONTEXT: Return raw context snippets for downstream processing
    - NARRATIVE: Generate LLM-synthesized narrative answer
    """

    def __init__(
        self,
        llm: LLMClient,
        max_context_tokens: int = 8000,
        narrative_max_tokens: int = 1024,
    ) -> None:
        """Initialize the narrative synthesizer.

        Args:
            llm: LLM client for narrative synthesis.
            max_context_tokens: Maximum tokens for context input.
            narrative_max_tokens: Maximum tokens for narrative output.
        """
        self._llm = llm
        self._max_context_tokens = max_context_tokens
        self._narrative_max_tokens = narrative_max_tokens

    async def synthesize(
        self,
        query: str,
        context_nodes: list[dict[str, Any]],
        mode: OutputMode = OutputMode.CONTEXT,
        include_provenance: bool = True,
    ) -> SynthesisResult:
        """Synthesize context into output format.

        Args:
            query: The original query.
            context_nodes: Retrieved context nodes with content and scores.
            mode: Output mode (CONTEXT or NARRATIVE).
            include_provenance: Whether to include source references.

        Returns:
            SynthesisResult with synthesized output.
        """
        log.info(
            "synthesis_started",
            query=query[:50],
            mode=mode.value,
            nodes=len(context_nodes),
        )

        if not context_nodes:
            return SynthesisResult(
                output="No relevant information found.",
                mode=mode,
                node_count=0,
            )

        try:
            if mode == OutputMode.CONTEXT:
                return await self._synthesize_context(
                    context_nodes=context_nodes,
                    include_provenance=include_provenance,
                )
            elif mode == OutputMode.NARRATIVE:
                return await self._synthesize_narrative(
                    query=query,
                    context_nodes=context_nodes,
                    include_provenance=include_provenance,
                )
            else:
                log.warning("unknown_output_mode", mode=mode)
                return SynthesisResult(
                    output="Unknown output mode.",
                    mode=mode,
                    node_count=len(context_nodes),
                )

        except Exception as exc:
            #: never echo the raw exception into the output — it may
            # carry internal paths/SQL. Full detail goes to the error log only.
            log.error(
                "synthesis_failed",
                query=query[:50],
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return SynthesisResult(
                output="Synthesis failed due to an internal error.",
                mode=mode,
                node_count=len(context_nodes),
            )

    async def _synthesize_context(
        self,
        context_nodes: list[dict[str, Any]],
        include_provenance: bool,
    ) -> SynthesisResult:
        """Synthesize context mode: return formatted snippets.

        Args:
            context_nodes: Retrieved context nodes.
            include_provenance: Whether to include source references.

        Returns:
            SynthesisResult with formatted context.
        """
        parts: list[str] = []
        included_nodes: list[str] = []
        current_tokens = 0

        for node in context_nodes:
            node_id = node.get("id", "unknown")
            content = node.get("content", "")
            score = node.get("score", 0.0)
            source = node.get("source", "")

            # Estimate tokens (rough: 4 chars per token)
            node_tokens = len(content) // 4

            if current_tokens + node_tokens > self._max_context_tokens:
                # Would exceed budget, summarize remaining
                break

            # Format snippet
            snippet_parts = [f"[Score: {score:.2f}]"]
            if include_provenance and source:
                snippet_parts.append(f"[Source: {source}]")
            snippet_parts.append(content)

            parts.append("\n".join(snippet_parts))
            included_nodes.append(node_id)
            current_tokens += node_tokens

        if not parts and context_nodes:
            # First node alone exceeds the token budget: include it truncated
            # instead of returning a misleading empty output with node_count=0.
            first = context_nodes[0]
            first_id = first.get("id", "unknown")
            budget_chars = max(self._max_context_tokens * 4, 200)
            truncated = first.get("content", "")[:budget_chars]
            log.warning(
                "context_budget_overflow",
                node_id=first_id,
                max_context_tokens=self._max_context_tokens,
            )
            parts.append(f"[Score: {first.get('score', 0.0):.2f}]\n{truncated}\n[truncated]")
            included_nodes.append(first_id)
            current_tokens = len(truncated) // 4

        output = "\n\n---\n\n".join(parts)

        # Nodes not included due to budget
        all_ids = [n.get("id", "unknown") for n in context_nodes]
        included_set = set(included_nodes)
        summarized_nodes = [nid for nid in all_ids if nid not in included_set]

        return SynthesisResult(
            output=output,
            mode=OutputMode.CONTEXT,
            total_tokens=current_tokens,
            node_count=len(included_nodes),
            included_nodes=included_nodes,
            summarized_nodes=summarized_nodes,
        )

    async def _synthesize_narrative(
        self,
        query: str,
        context_nodes: list[dict[str, Any]],
        include_provenance: bool,
    ) -> SynthesisResult:
        """Synthesize narrative mode: LLM-generated answer.

        Args:
            query: The original query.
            context_nodes: Retrieved context nodes.
            include_provenance: Whether to include source references.

        Returns:
            SynthesisResult with narrative answer.
        """
        # Build context string
        context_parts: list[str] = []
        included_nodes: list[str] = []
        current_tokens = 0

        for node in context_nodes:
            node_id = node.get("id", "unknown")
            content = node.get("content", "")
            source = node.get("source", "")

            node_tokens = len(content) // 4

            if current_tokens + node_tokens > self._max_context_tokens:
                break

            if include_provenance and source:
                context_parts.append(f"[{source}] {content}")
            else:
                context_parts.append(content)

            included_nodes.append(node_id)
            current_tokens += node_tokens

        if not context_parts and context_nodes:
            first = context_nodes[0]
            first_id = first.get("id", "unknown")
            budget_chars = max(self._max_context_tokens * 4, 200)
            truncated = first.get("content", "")[:budget_chars]
            log.warning(
                "narrative_budget_overflow",
                node_id=first_id,
                max_context_tokens=self._max_context_tokens,
            )
            context_parts.append(f"{truncated}\n[truncated]")
            included_nodes.append(first_id)
            current_tokens = len(truncated) // 4

        context_str = "\n\n".join(context_parts)

        # Call LLM for synthesis
        fallback = False
        try:
            response = await self._llm.call_at(
                call_point="narrative_synthesis",
                payload={
                    "query": query,
                    "context": context_str,
                    "max_tokens": self._narrative_max_tokens,
                },
            )

            if isinstance(response, dict):
                narrative = response.get("answer")
                if not isinstance(narrative, str):
                    # Missing/odd "answer" key must not stringify the whole
                    # payload (context, tokens…) into user-visible output.
                    log.warning(
                        "narrative_answer_key_missing",
                        response_keys=sorted(response.keys()),
                    )
                    narrative = ""
                tokens_used = response.get("tokens_used", current_tokens)
            else:
                narrative = str(response)
                tokens_used = current_tokens

        except Exception as exc:
            log.warning(
                "narrative_llm_failed",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            # Fallback serves raw context, so label it CONTEXT — callers
            # expecting a synthesized narrative must not mistake it.
            narrative = context_str
            tokens_used = current_tokens
            fallback = True

        all_ids = [n.get("id", "unknown") for n in context_nodes]
        included_set = set(included_nodes)
        summarized_nodes = [nid for nid in all_ids if nid not in included_set]

        return SynthesisResult(
            output=narrative,
            mode=OutputMode.CONTEXT if fallback else OutputMode.NARRATIVE,
            total_tokens=tokens_used,
            node_count=len(included_nodes),
            included_nodes=included_nodes,
            summarized_nodes=summarized_nodes,
        )
