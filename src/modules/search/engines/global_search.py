# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Global search engine using Map-Reduce pattern.

Performs community-level searches with aggregation, suitable for
broad, exploratory queries that span multiple communities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.db.neo4j import Neo4jPool
from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from modules.search.context.global_context import GlobalContextBuilder
from modules.search.engines.local_search import SearchResult

log = get_logger("search.global_engine")


@dataclass
class MapReduceResult:
    """Result from Map-Reduce search operation."""

    query: str
    final_answer: str
    intermediate_answers: list[str]
    context_tokens: int
    communities_searched: int
    confidence: float
    metadata: dict[str, Any]


class GlobalSearchEngine:
    """Global search engine using Map-Reduce pattern.

    This engine:
    1. Identifies relevant communities
    2. Generates intermediate answers for each community (Map)
    3. Aggregates into a final comprehensive answer (Reduce)

    Best for:
    - Broad queries ("What are the main themes?")
    - Comparative queries ("Compare X and Y")
    - Exploratory queries ("Tell me about topic Z")
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        llm: LLMClient,
        default_max_tokens: int = 12000,
        max_communities: int = 10,
    ) -> None:
        """Initialize global search engine.

        Args:
            neo4j_pool: Neo4j connection pool.
            llm: LLM client for answer generation.
            default_max_tokens: Default max tokens for context.
            max_communities: Maximum communities to process.
        """
        self._pool = neo4j_pool
        self._llm = llm
        self._default_max_tokens = default_max_tokens
        self._max_communities = max_communities
        self._context_builder = GlobalContextBuilder(
            neo4j_pool=neo4j_pool,
            default_max_tokens=default_max_tokens,
            max_communities=max_communities,
        )

    async def search(
        self,
        query: str,
        max_tokens: int | None = None,
        community_level: int = 0,
        use_llm: bool = True,
        **kwargs: Any,
    ) -> SearchResult:
        """Perform a global search.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for context.
            community_level: Community hierarchy level.
            use_llm: Whether to use LLM for answer generation.
            **kwargs: Additional parameters.

        Returns:
            SearchResult with the aggregated answer.
        """
        max_tokens = max_tokens or self._default_max_tokens

        try:
            contexts = await self._context_builder.build_map_reduce_context(
                query=query,
                max_tokens_per_community=max_tokens // self._max_communities,
                community_level=community_level,
            )

            if not contexts:
                return SearchResult(
                    query=query,
                    answer="No relevant communities found for the query.",
                    context_tokens=0,
                    confidence=0.0,
                    metadata={"search_type": "global", "communities": 0},
                )

            # If use_llm=False, return context without LLM generation
            if not use_llm:
                return SearchResult(
                    query=query,
                    answer=f"Found {len(contexts)} relevant communities. LLM generation skipped.",
                    context_tokens=sum(c.total_tokens for c in contexts),
                    confidence=self._estimate_confidence([]),
                    metadata={
                        "search_type": "global",
                        "communities": len(contexts),
                        "llm_used": False,
                    },
                )

            intermediate_answers = []
            total_tokens = 0

            for i, context in enumerate(contexts):
                map_prompt = self._build_map_prompt(query, context)

                response = await self._llm.call(
                    call_point=CallPoint.SEARCH_GLOBAL,
                    payload={
                        "query": query,
                        "context": map_prompt,
                        "phase": "map",
                        "community_index": i,
                    },
                )

                answer = response if isinstance(response, str) else str(response)
                intermediate_answers.append(answer)
                total_tokens += context.total_tokens

            reduce_prompt = self._build_reduce_prompt(query, intermediate_answers)

            final_response = await self._llm.call(
                call_point=CallPoint.SEARCH_GLOBAL,
                payload={
                    "query": query,
                    "intermediate_answers": intermediate_answers,
                    "context": reduce_prompt,
                    "phase": "reduce",
                },
            )

            final_answer = (
                final_response if isinstance(final_response, str) else str(final_response)
            )

            return SearchResult(
                query=query,
                answer=final_answer,
                context_tokens=total_tokens,
                sources=[],
                entities=[],
                confidence=self._estimate_confidence(intermediate_answers),
                metadata={
                    "search_type": "global",
                    "communities": len(contexts),
                    "community_level": community_level,
                    "intermediate_count": len(intermediate_answers),
                    "llm_used": True,
                },
            )

        except Exception as exc:
            log.error("global_search_failed", error=str(exc))
            return SearchResult(
                query=query,
                answer=f"Search failed: {exc!s}",
                context_tokens=0,
                confidence=0.0,
                metadata={"error": str(exc)},
            )

    def _build_map_prompt(self, query: str, context: Any) -> str:
        """Build the Map phase prompt."""
        context_prompt = context.to_prompt()

        return f"""You are analyzing a specific community within a knowledge graph.

Based on the community context below, provide a focused answer to the question.
Focus on information specific to this community.

Community Context:
{context_prompt}

Question: {query}

Provide a concise answer focusing on this community's perspective:

Answer:"""

    def _build_reduce_prompt(self, query: str, intermediate_answers: list[str]) -> str:
        """Build the Reduce phase prompt."""
        answers_text = "\n\n---\n\n".join(
            [f"Perspective {i+1}:\n{answer}" for i, answer in enumerate(intermediate_answers)]
        )

        return f"""You are synthesizing multiple perspectives into a comprehensive answer.

The following perspectives come from different communities in a knowledge graph.
Synthesize them into a coherent, comprehensive answer to the question.

Question: {query}

Perspectives:
{answers_text}

Instructions:
1. Synthesize the perspectives into a unified answer
2. Highlight key themes and patterns across communities
3. Note any contradictions or differences
4. Be comprehensive but avoid repetition

Comprehensive Answer:"""

    def _estimate_confidence(self, intermediate_answers: list[str]) -> float:
        """Estimate confidence based on intermediate answers."""
        if not intermediate_answers:
            return 0.0

        confidence = 0.5

        if len(intermediate_answers) >= 3:
            confidence += 0.1

        total_length = sum(len(a) for a in intermediate_answers)
        if total_length > 500:
            confidence += 0.2
        elif total_length > 200:
            confidence += 0.1

        non_empty = sum(1 for a in intermediate_answers if a.strip())
        if non_empty == len(intermediate_answers):
            confidence += 0.1

        return min(1.0, confidence)

    async def search_simple(
        self,
        query: str,
        max_tokens: int | None = None,
        community_level: int = 0,
        use_llm: bool = True,
    ) -> SearchResult:
        """Perform a simplified global search without Map-Reduce.

        Uses a single context with community summaries.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for context.
            community_level: Community hierarchy level.
            use_llm: Whether to use LLM for answer generation.

        Returns:
            SearchResult with the answer.
        """
        max_tokens = max_tokens or self._default_max_tokens

        context = await self._context_builder.build(
            query=query,
            max_tokens=max_tokens,
            community_level=community_level,
        )

        # If use_llm=False, return context without LLM generation
        if not use_llm:
            return SearchResult(
                query=query,
                answer=f"Found {context.metadata.get('total_communities', 0)} communities. LLM generation skipped.",
                context_tokens=context.total_tokens,
                confidence=self._estimate_simple_confidence(context),
                metadata={
                    "search_type": "global_simple",
                    "communities": context.metadata.get("total_communities", 0),
                    "llm_used": False,
                },
            )

        prompt = self._build_simple_prompt(query, context)

        try:
            response = await self._llm.call(
                call_point=CallPoint.SEARCH_GLOBAL,
                payload={"query": query, "context": prompt},
            )

            answer = response if isinstance(response, str) else str(response)

            return SearchResult(
                query=query,
                answer=answer,
                context_tokens=context.total_tokens,
                sources=[],
                entities=[],
                confidence=self._estimate_simple_confidence(context),
                metadata={
                    "search_type": "global_simple",
                    "communities": context.metadata.get("total_communities", 0),
                    "llm_used": True,
                },
            )

        except Exception as exc:
            log.error("simple_global_search_failed", error=str(exc))
            return SearchResult(
                query=query,
                answer=f"Search failed: {exc!s}",
                context_tokens=0,
                confidence=0.0,
                metadata={"error": str(exc)},
            )

    def _build_simple_prompt(self, query: str, context: Any) -> str:
        """Build prompt for simple global search."""
        context_prompt = context.to_prompt()

        return f"""You are answering a question based on community-level knowledge graph summaries.

Use the provided community summaries to answer the question comprehensively.

Context:
{context_prompt}

Question: {query}

Instructions:
1. Synthesize information across communities
2. Identify key themes and patterns
3. Provide a comprehensive answer

Answer:"""

    def _estimate_simple_confidence(self, context: Any) -> float:
        """Estimate confidence for simple search."""
        if not context.sections:
            return 0.0

        community_count = context.metadata.get("total_communities", 0)

        confidence = 0.4

        if community_count >= 3:
            confidence += 0.2
        elif community_count >= 1:
            confidence += 0.1

        if context.total_tokens > 1000:
            confidence += 0.2

        return min(1.0, confidence)
