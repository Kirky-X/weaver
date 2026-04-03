# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Narrative Synthesizer for MAGMA multi-graph memory.

Synthesizes retrieved context into coherent narratives using LLM.
Implements the NarrativeSynthesizer component from MAGMA specification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability.logging import get_logger
from modules.memory.core.graph_types import OutputMode, SynthesisResult

if TYPE_CHECKING:
    from core.llm.client import LLMClient

log = get_logger("narrative_synthesizer")


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
                    query=query,
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
            log.error("synthesis_failed", query=query[:50], error=str(exc))
            return SynthesisResult(
                output=f"Synthesis failed: {exc}",
                mode=mode,
                node_count=len(context_nodes),
            )

    async def _synthesize_context(
        self,
        query: str,
        context_nodes: list[dict[str, Any]],
        include_provenance: bool,
    ) -> SynthesisResult:
        """Synthesize context mode: return formatted snippets.

        Args:
            query: The original query.
            context_nodes: Retrieved context nodes.
            include_provenance: Whether to include source references.

        Returns:
            SynthesisResult with formatted context.
        """
        parts: list[str] = []
        included_nodes: list[str] = []
        total_tokens = 0
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
            total_tokens = current_tokens

        output = "\n\n---\n\n".join(parts)

        # Nodes not included due to budget
        all_ids = [n.get("id", "unknown") for n in context_nodes]
        summarized_nodes = [nid for nid in all_ids if nid not in included_nodes]

        return SynthesisResult(
            output=output,
            mode=OutputMode.CONTEXT,
            total_tokens=total_tokens,
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

        context_str = "\n\n".join(context_parts)

        # Call LLM for synthesis
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
                narrative = response.get("answer", str(response))
                tokens_used = response.get("tokens_used", current_tokens)
            else:
                narrative = str(response)
                tokens_used = current_tokens

        except Exception as exc:
            log.warning("narrative_llm_failed", error=str(exc))
            # Fallback to context mode
            narrative = context_str
            tokens_used = current_tokens

        all_ids = [n.get("id", "unknown") for n in context_nodes]
        summarized_nodes = [nid for nid in all_ids if nid not in included_nodes]

        return SynthesisResult(
            output=narrative,
            mode=OutputMode.NARRATIVE,
            total_tokens=tokens_used,
            node_count=len(included_nodes),
            included_nodes=included_nodes,
            summarized_nodes=summarized_nodes,
        )
