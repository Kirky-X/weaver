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
from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from modules.knowledge.search.engines.local_search import SearchResult

if TYPE_CHECKING:
    from modules.knowledge.search.engines.hybrid_search import HybridSearchEngine

log = get_logger(__name__)


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
        context_builder: Any,
        llm: LLMClient | None = None,
        default_max_tokens: int = 12000,
        max_communities: int = 10,
        hybrid_engine: HybridSearchEngine | None = None,
        local_engine: Any = None,
    ) -> None:
        """Initialize global search engine.

        Args:
            context_builder: ContextBuilder instance for building search context.
            llm: LLM client for answer generation.
            default_max_tokens: Default max tokens for context.
            max_communities: Maximum communities to process.
            hybrid_engine: Optional hybrid search engine for enhanced retrieval.
            local_engine: Optional local search engine for fallback when no relevant communities found.
        """
        self._llm = llm
        self._default_max_tokens = default_max_tokens
        self._max_communities = max_communities
        self._hybrid_engine = hybrid_engine
        self._local = local_engine
        self._context_builder = context_builder
        # Extract pool from context_builder for DRIFT search compatibility
        self._pool = getattr(context_builder, "_pool", None)

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

                # Communities exist but none are relevant - fall back to local search
                if self._local is not None:
                    log.info("global_search_fallback_to_local", query=query)
                    local_result = await self._local.search(query=query, use_llm=use_llm)
                    if isinstance(local_result, dict):
                        local_result["metadata"] = {
                            **local_result.get("metadata", {}),
                            "search_type": SearchMode.HYBRID.value,
                            "fallback_from_global": True,
                        }
                        return local_result
                    elif hasattr(local_result, "metadata"):
                        local_result.metadata["search_type"] = SearchMode.HYBRID.value
                        local_result.metadata["fallback_from_global"] = True
                        return local_result

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
                community_scores = [c.similarity_score for c in communities]
                return SearchResult(
                    query=query,
                    answer=f"Found {len(communities)} relevant communities. LLM generation skipped.",
                    context_tokens=total_tokens,
                    confidence=self._estimate_confidence([], community_scores),
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
                        "top_community_score": community_scores[0] if community_scores else 0,
                    },
                )

            # Sort communities by similarity score (weight) and limit to top 3
            # to avoid excessive LLM calls causing timeouts
            sorted_communities = sorted(
                communities,
                key=lambda c: c.similarity_score,
                reverse=True,
            )[
                :3
            ]  # Limit to top 3 communities for faster response

            intermediate_answers = []
            total_tokens = 0
            community_weights = []

            # Parallel LLM calls with semaphore for rate limiting and timeout
            semaphore = asyncio.Semaphore(3)  # Reduced concurrent LLM calls

            async def process_community(
                idx: int, community: CommunityContext
            ) -> tuple[int, str, dict[str, Any], int]:
                """Process a single community with semaphore and timeout."""
                async with semaphore:
                    map_prompt = self._build_map_prompt(query, community)
                    try:
                        # Add timeout to individual LLM call
                        response = await asyncio.wait_for(
                            self._llm.call(
                                label="chat.aiping.GLM-4-9B-0414",
                                call_point=CallPoint.SEARCH_GLOBAL,
                                payload={
                                    "system_prompt": (
                                        "你是一个知识图谱分析专家，基于社区报告回答用户问题。请用简洁、准确的语言回答，仅使用中文。"
                                    ),
                                    "user_content": map_prompt,
                                },
                            ),
                            timeout=15.0,  # 15 second timeout per community
                        )
                        answer = response if isinstance(response, str) else str(response)
                    except TimeoutError:
                        log.warning("community_llm_timeout", community_id=community.id)
                        answer = f"[Timeout processing community: {community.title}]"
                    weight_info = {
                        "community_id": community.id,
                        "title": community.title,
                        "weight": community.similarity_score,
                    }
                    tokens = len(map_prompt) // 4
                    return idx, answer, weight_info, tokens

            # Execute all LLM calls in parallel with overall timeout
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(
                        *[process_community(i, c) for i, c in enumerate(sorted_communities)]
                    ),
                    timeout=30.0,  # 30 second overall timeout for Map phase
                )
            except TimeoutError:
                log.warning("global_search_map_timeout", query=query[:50])
                # Fallback: return simple context-based answer without LLM synthesis
                fallback_answer = "\n\n".join(
                    f"**{c.title}**\n{c.summary or c.full_content or 'No summary available'}"
                    for c in sorted_communities[:3]
                )
                return SearchResult(
                    query=query,
                    answer=fallback_answer,
                    context_tokens=sum(
                        len(c.full_content or c.summary or "") // 4 for c in sorted_communities
                    ),
                    sources=[],
                    entities=list(
                        set(e for c in sorted_communities if c.key_entities for e in c.key_entities)
                    ),
                    confidence=0.5,
                    metadata={
                        "search_type": SearchMode.GLOBAL.value,
                        "communities": len(sorted_communities),
                        "llm_used": False,
                        "timeout_fallback": True,
                    },
                )

            # Sort results by original index and extract data
            for idx, answer, weight_info, tokens in sorted(results, key=lambda r: r[0]):
                intermediate_answers.append(answer)
                community_weights.append(weight_info)
                total_tokens += tokens

            reduce_prompt = self._build_reduce_prompt(
                query, intermediate_answers, community_weights
            )

            # Reduce phase with timeout
            try:
                final_response = await asyncio.wait_for(
                    self._llm.call(
                        label="chat.aiping.GLM-4-9B-0414",
                        call_point=CallPoint.SEARCH_GLOBAL,
                        payload={
                            "system_prompt": (
                                "你是一个知识图谱分析专家，综合多个社区观点生成统一答案。请提供全面、平衡的回答，仅使用中文，不要包含任何英文或其他语言字符。"
                            ),
                            "user_content": reduce_prompt,
                        },
                    ),
                    timeout=15.0,  # 15 second timeout for Reduce phase
                )
                final_answer = (
                    final_response if isinstance(final_response, str) else str(final_response)
                )
                reduce_timeout_fallback = False
            except TimeoutError:
                log.warning("global_search_reduce_timeout", query=query[:50])
                # Fallback: concatenate intermediate answers
                final_answer = "\n\n".join(
                    f"**社区 {i + 1}观点:** {ans}" for i, ans in enumerate(intermediate_answers)
                )
                reduce_timeout_fallback = True

            # Collect community scores for confidence estimation
            community_scores = [c.similarity_score for c in sorted_communities]

            return SearchResult(
                query=query,
                answer=final_answer,
                context_tokens=total_tokens,
                sources=[],
                entities=list(
                    set(e for c in sorted_communities if c.key_entities for e in c.key_entities)
                ),
                confidence=self._estimate_confidence(intermediate_answers, community_scores),
                metadata={
                    "search_type": SearchMode.GLOBAL.value,
                    "communities": len(sorted_communities),
                    "community_level": community_level,
                    "intermediate_count": len(intermediate_answers),
                    "llm_used": not reduce_timeout_fallback,
                    "reduce_timeout_fallback": reduce_timeout_fallback,
                    "hybrid_used": self._hybrid_engine is not None,
                    "search_method": "vector_similarity",
                    "top_community_score": community_scores[0] if community_scores else 0,
                    "avg_community_score": (
                        sum(community_scores) / len(community_scores) if community_scores else 0
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
                    rank=comm.get("rank") or 1.0,
                    similarity_score=comm.get("similarity_score")
                    or (comm.get("rank") or 1.0) / 10.0,
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

    def _estimate_confidence(
        self,
        intermediate_answers: list[str],
        community_scores: list[float] | None = None,
    ) -> float:
        """Estimate confidence based on actual relevance scores and answer quality.

        Args:
            intermediate_answers: List of intermediate LLM answers.
            community_scores: List of community similarity scores (0-1 range).

        Returns:
            Confidence score (0-1 range).
        """
        if not intermediate_answers:
            return 0.0

        # Base confidence from actual relevance scores (primary factor)
        if community_scores:
            # Weight confidence heavily by the top community score
            top_score = max(community_scores)
            avg_score = sum(community_scores) / len(community_scores)

            # High relevance scores boost confidence significantly
            # top_score is primary indicator, avg_score provides consistency check
            confidence = top_score * 0.6 + avg_score * 0.2

            # Score consistency bonus: low variance means more coherent results
            if len(community_scores) >= 2:
                variance = sum((s - avg_score) ** 2 for s in community_scores) / len(
                    community_scores
                )
                # Lower variance = higher consistency = higher confidence
                consistency_bonus = max(0, 0.15 - variance * 0.3)
                confidence += consistency_bonus
        else:
            # Fallback: no scores available, use conservative estimate
            confidence = 0.3

        # Secondary factors from answer quality (minor adjustments)
        total_length = sum(len(a) for a in intermediate_answers)
        if total_length > 500:
            confidence += 0.05  # Reduced bonus, content quality matters more than length
        elif total_length > 200:
            confidence += 0.02

        # Non-empty answers bonus
        non_empty = sum(1 for a in intermediate_answers if a.strip())
        if non_empty == len(intermediate_answers):
            confidence += 0.03

        return min(1.0, max(0.0, confidence))

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
                label="chat.aiping.GLM-4-9B-0414",
                call_point=CallPoint.SEARCH_GLOBAL,
                payload={
                    "system_prompt": (
                        "你是一个知识图谱分析专家，基于给定的上下文回答问题。仅使用中文回答。"
                    ),
                    "user_content": prompt,
                },
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
