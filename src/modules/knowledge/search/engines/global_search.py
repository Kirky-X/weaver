# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Global search engine using Map-Reduce pattern.

Performs community-level searches with aggregation, suitable for
broad, exploratory queries that span multiple communities.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.constants import SearchMode
from core.db.neo4j import Neo4jPool
from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from modules.knowledge.search.context.global_context import GlobalContextBuilder
from modules.knowledge.search.engines.local_search import SearchResult

if TYPE_CHECKING:
    from modules.knowledge.search.engines.hybrid_search import HybridSearchEngine

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


@dataclass
class CommunityContext:
    """Context for a single community in Map-Reduce."""

    id: str
    title: str
    summary: str
    entity_count: int
    rank: float
    similarity_score: float
    full_content: str | None = None
    key_entities: list[str] | None = None
    entities: list[dict[str, Any]] | None = None


class GlobalSearchEngine:
    """Global search engine using Map-Reduce pattern.

    This engine:
    1. Identifies relevant communities using vector similarity
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
        hybrid_engine: HybridSearchEngine | None = None,
    ) -> None:
        """Initialize global search engine.

        Args:
            neo4j_pool: Neo4j connection pool.
            llm: LLM client for answer generation.
            default_max_tokens: Default max tokens for context.
            max_communities: Maximum communities to process.
            hybrid_engine: Optional hybrid search engine for enhanced retrieval.
        """
        self._pool = neo4j_pool
        self._llm = llm
        self._default_max_tokens = default_max_tokens
        self._max_communities = max_communities
        self._hybrid_engine = hybrid_engine
        self._context_builder = GlobalContextBuilder(
            neo4j_pool=neo4j_pool,
            default_max_tokens=default_max_tokens,
            max_communities=max_communities,
            llm_client=llm,
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
            # Get community contexts with full reports
            communities = await self._get_community_contexts(
                query=query,
                level=community_level,
            )

            if not communities:
                # Check if there are any communities at all
                has_communities = await self._has_any_communities(community_level)
                if not has_communities:
                    return SearchResult(
                        query=query,
                        answer="社区数据尚未初始化，请先执行社区检测。",
                        context_tokens=0,
                        confidence=0.0,
                        metadata={
                            "search_type": SearchMode.GLOBAL.value,
                            "communities": 0,
                            "hint": "run POST /api/v1/admin/communities/rebuild",
                        },
                    )
                return SearchResult(
                    query=query,
                    answer="No relevant communities found for the query.",
                    context_tokens=0,
                    confidence=0.0,
                    metadata={
                        "search_type": SearchMode.GLOBAL.value,
                        "communities": 0,
                        "hybrid_used": self._hybrid_engine is not None,
                    },
                )

            # If use_llm=False, return context without LLM generation
            if not use_llm:
                total_tokens = sum(len(c.full_content or c.summary) // 4 for c in communities)
                return SearchResult(
                    query=query,
                    answer=f"Found {len(communities)} relevant communities. LLM generation skipped.",
                    context_tokens=total_tokens,
                    confidence=self._estimate_confidence([]),
                    entities=list(
                        set(e for c in communities if c.key_entities for e in c.key_entities)
                    ),
                    metadata={
                        "search_type": SearchMode.GLOBAL.value,
                        "communities": len(communities),
                        "llm_used": False,
                        "hybrid_used": self._hybrid_engine is not None,
                        "search_method": "vector_similarity",
                        "community_level": community_level,
                    },
                )

            # Sort communities by similarity score (weight)
            sorted_communities = sorted(
                communities,
                key=lambda c: c.similarity_score,
                reverse=True,
            )

            intermediate_answers = []
            total_tokens = 0
            community_weights = []

            # Parallel LLM calls with semaphore for rate limiting
            semaphore = asyncio.Semaphore(5)  # Limit concurrent LLM calls

            async def process_community(
                idx: int, community: CommunityContext
            ) -> tuple[int, str, dict[str, Any], int]:
                """Process a single community with semaphore."""
                async with semaphore:
                    map_prompt = self._build_map_prompt(query, community)
                    response = await self._llm.call(
                        call_point=CallPoint.SEARCH_GLOBAL,
                        payload={
                            "query": query,
                            "context": map_prompt,
                            "phase": "map",
                            "community_index": idx,
                            "community_title": community.title,
                            "community_weight": community.similarity_score,
                        },
                    )
                    answer = response if isinstance(response, str) else str(response)
                    weight_info = {
                        "community_id": community.id,
                        "title": community.title,
                        "weight": community.similarity_score,
                    }
                    tokens = len(map_prompt) // 4
                    return idx, answer, weight_info, tokens

            # Execute all LLM calls in parallel
            results = await asyncio.gather(
                *[process_community(i, c) for i, c in enumerate(sorted_communities)]
            )

            # Sort results by original index and extract data
            for idx, answer, weight_info, tokens in sorted(results, key=lambda r: r[0]):
                intermediate_answers.append(answer)
                community_weights.append(weight_info)
                total_tokens += tokens

            reduce_prompt = self._build_reduce_prompt(
                query, intermediate_answers, community_weights
            )

            final_response = await self._llm.call(
                call_point=CallPoint.SEARCH_GLOBAL,
                payload={
                    "query": query,
                    "intermediate_answers": intermediate_answers,
                    "context": reduce_prompt,
                    "phase": "reduce",
                    "community_weights": community_weights,
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
                entities=list(
                    set(e for c in sorted_communities if c.key_entities for e in c.key_entities)
                ),
                confidence=self._estimate_confidence(intermediate_answers),
                metadata={
                    "search_type": SearchMode.GLOBAL.value,
                    "communities": len(sorted_communities),
                    "community_level": community_level,
                    "intermediate_count": len(intermediate_answers),
                    "llm_used": True,
                    "hybrid_used": self._hybrid_engine is not None,
                    "search_method": "vector_similarity",
                    "top_community_score": (
                        sorted_communities[0].similarity_score if sorted_communities else 0
                    ),
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

    async def _get_community_contexts(
        self,
        query: str,
        level: int,
    ) -> list[CommunityContext]:
        """Get community contexts with full reports from vector search.

        Args:
            query: The search query.
            level: Community hierarchy level.

        Returns:
            List of CommunityContext with report content.
        """
        (
            communities,
            used_fallback,
            search_method,
        ) = await self._context_builder._find_relevant_communities(query, level)

        if not communities:
            return []

        contexts = []
        for comm in communities:
            # Get entities for this community
            entities = await self._context_builder._get_community_entities(comm.get("id", ""))

            contexts.append(
                CommunityContext(
                    id=comm.get("id", ""),
                    title=comm.get("title", "Unknown"),
                    summary=comm.get("summary", ""),
                    entity_count=comm.get("entity_count", 0),
                    rank=comm.get("rank", 1.0),
                    similarity_score=comm.get("similarity_score", comm.get("rank", 1.0) / 10.0),
                    full_content=comm.get("full_content"),
                    key_entities=comm.get("key_entities", []),
                    entities=entities,
                )
            )

        return contexts

    async def _has_any_communities(self, level: int | None = None) -> bool:
        """Check if any communities exist in the graph."""
        return await self._context_builder._has_any_communities(level)

    def _build_map_prompt(self, query: str, community: CommunityContext) -> str:
        """Build the Map phase prompt using full community report.

        Args:
            query: The search query.
            community: Community context with report.

        Returns:
            Formatted prompt for Map phase.
        """
        # Use full community report if available
        if community.full_content:
            context = f"""## Community: {community.title}

### Community Report
{community.full_content}

### Key Entities
{", ".join(community.key_entities) if community.key_entities else "N/A"}

### Statistics
- Entity Count: {community.entity_count}
- Relevance Score: {community.similarity_score:.2f}
"""
        else:
            # Fallback to summary
            context = f"""## Community: {community.title}

### Summary
{community.summary}

### Statistics
- Entity Count: {community.entity_count}
- Relevance Score: {community.similarity_score:.2f}
"""

        return f"""You are analyzing a specific community within a knowledge graph.

Based on the community report below, provide a focused answer to the question.
Focus on information specific to this community and cite key entities when relevant.

{context}

Question: {query}

Provide a concise answer focusing on this community's perspective:

Answer:"""

    def _build_reduce_prompt(
        self,
        query: str,
        intermediate_answers: list[str],
        community_weights: list[dict[str, Any]],
    ) -> str:
        """Build the Reduce phase prompt with community weights.

        Args:
            query: The search query.
            intermediate_answers: List of intermediate answers from Map phase.
            community_weights: List of community weights for ranking.

        Returns:
            Formatted prompt for Reduce phase.
        """
        # Build weighted perspectives
        weighted_answers = []
        for i, (answer, weight_info) in enumerate(zip(intermediate_answers, community_weights)):
            weight = weight_info.get("weight", 1.0)
            title = weight_info.get("title", f"Community {i + 1}")
            weighted_answers.append(
                f"### Perspective {i + 1}: {title}\n(Relevance: {weight:.2f})\n\n{answer}"
            )

        answers_text = "\n\n---\n\n".join(weighted_answers)

        # Determine sorting guidance
        sorted_by_weight = sorted(community_weights, key=lambda x: x.get("weight", 0), reverse=True)
        top_community = sorted_by_weight[0]["title"] if sorted_by_weight else "N/A"

        return f"""You are synthesizing multiple perspectives into a comprehensive answer.

The following perspectives come from different communities in a knowledge graph.
Each perspective has a relevance score indicating how well it matches the query.
Prioritize information from higher-scoring perspectives, but include relevant
information from all perspectives.

Question: {query}

Perspectives (sorted by relevance):
{answers_text}

**Most Relevant Community: {top_community}**

Instructions:
1. Synthesize the perspectives into a unified, comprehensive answer
2. Prioritize information from higher-scoring perspectives
3. Highlight key themes and patterns across communities
4. Note any important differences or contradictions
5. Be comprehensive but avoid repetition
6. Cite specific communities or entities when relevant

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
                    "hybrid_used": self._hybrid_engine is not None,
                    "search_method": context.metadata.get("search_method", "unknown"),
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
                    "hybrid_used": self._hybrid_engine is not None,
                    "search_method": context.metadata.get("search_method", "unknown"),
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
