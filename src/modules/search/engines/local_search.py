# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Local search engine for entity-based neighborhood search.

Performs targeted searches around specific entities, suitable for
precise, factual queries that require detailed entity information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.db.neo4j import Neo4jPool
from core.llm.client import LLMClient
from core.llm.types import CallPoint
from core.observability.logging import get_logger
from modules.search.context.local_context import LocalContextBuilder

if TYPE_CHECKING:
    from modules.search.engines.hybrid_search import HybridSearchEngine

log = get_logger("search.local_engine")


@dataclass
class SearchResult:
    """Result from a search operation."""

    query: str
    answer: str
    context_tokens: int
    sources: list[dict[str, Any]] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalSearchEngine:
    """Local search engine for entity-focused queries.

    This engine:
    1. Identifies relevant entities from the query
    2. Builds local context around those entities
    3. Uses LLM to generate an answer from the context

    Best for:
    - Specific entity queries ("Who is X?")
    - Relationship queries ("How are X and Y connected?")
    - Factual queries about known entities
    """

    def __init__(
        self,
        neo4j_pool: Neo4jPool,
        llm: LLMClient,
        default_max_tokens: int = 8000,
        max_context_tokens: int = 6000,
        hybrid_engine: HybridSearchEngine | None = None,
    ) -> None:
        """Initialize local search engine.

        Args:
            neo4j_pool: Neo4j connection pool.
            llm: LLM client for answer generation.
            default_max_tokens: Default max tokens for context.
            max_context_tokens: Maximum tokens for context window.
            hybrid_engine: Optional hybrid search engine for enhanced retrieval.
        """
        self._pool = neo4j_pool
        self._llm = llm
        self._default_max_tokens = default_max_tokens
        self._max_context_tokens = max_context_tokens
        self._hybrid_engine = hybrid_engine
        self._context_builder = LocalContextBuilder(
            neo4j_pool=neo4j_pool,
            default_max_tokens=default_max_tokens,
        )

    async def search(
        self,
        query: str,
        max_tokens: int | None = None,
        entity_names: list[str] | None = None,
        use_llm: bool = True,
        **kwargs: Any,
    ) -> SearchResult:
        """Perform a local search.

        Args:
            query: The search query.
            max_tokens: Maximum tokens for context.
            entity_names: Optional list of entities to focus on.
            use_llm: Whether to use LLM for answer generation.
            **kwargs: Additional parameters.

        Returns:
            SearchResult with the answer and metadata.
        """
        max_tokens = max_tokens or self._default_max_tokens

        context = await self._context_builder.build(
            query=query,
            max_tokens=min(max_tokens, self._max_context_tokens),
            entity_names=entity_names,
        )

        # If use_llm=False, return context without LLM generation
        if not use_llm:
            entities = self._extract_entities_from_context(context)
            return SearchResult(
                query=query,
                answer="Context built successfully. LLM generation skipped.",
                context_tokens=context.total_tokens,
                sources=context.metadata.get("article_count", 0),
                entities=entities,
                confidence=self._estimate_confidence(context),
                metadata={
                    "context_sections": len(context.sections),
                    "search_type": "local",
                    "llm_used": False,
                    "hybrid_used": self._hybrid_engine is not None,
                },
            )

        prompt = self._build_prompt(query, context)

        try:
            response = await self._llm.call(
                call_point=CallPoint.SEARCH_LOCAL,
                payload={"query": query, "context": prompt},
            )

            answer = response if isinstance(response, str) else str(response)

            entities = self._extract_entities_from_context(context)

            return SearchResult(
                query=query,
                answer=answer,
                context_tokens=context.total_tokens,
                sources=context.metadata.get("article_count", 0),
                entities=entities,
                confidence=self._estimate_confidence(context),
                metadata={
                    "context_sections": len(context.sections),
                    "search_type": "local",
                    "llm_used": True,
                    "hybrid_used": self._hybrid_engine is not None,
                },
            )

        except Exception as exc:
            log.error("local_search_failed", error=str(exc))
            return SearchResult(
                query=query,
                answer=f"Search failed: {exc!s}",
                context_tokens=0,
                confidence=0.0,
                metadata={"error": str(exc)},
            )

    def _build_prompt(self, query: str, context: Any) -> str:
        """Build the LLM prompt from context."""
        context_prompt = context.to_prompt()

        return f"""You are a helpful assistant answering questions based on a knowledge graph.

Use the provided context to answer the question accurately. If the context doesn't contain
enough information, say so clearly.

Context:
{context_prompt}

Question: {query}

Instructions:
1. Answer based only on the provided context
2. Cite specific entities and relationships when relevant
3. If information is incomplete, acknowledge the limitations
4. Be concise but comprehensive

Answer:"""

    def _extract_entities_from_context(self, context: Any) -> list[str]:
        """Extract entity names from context."""
        entities = []
        for section in context.sections:
            if section.metadata.get("entity_count"):
                content = section.content
                for line in content.split("\n"):
                    if line.startswith("- ") and "(" in line:
                        name = line[2:].split("(")[0].strip()
                        if name:
                            entities.append(name)
        return list(set(entities))[:20]

    def _estimate_confidence(self, context: Any) -> float:
        """Estimate confidence based on context quality."""
        if not context.sections:
            return 0.0

        entity_count = context.metadata.get("total_entities", 0)
        rel_count = context.metadata.get("total_relationships", 0)

        confidence = 0.5

        if entity_count > 0:
            confidence += min(0.2, entity_count * 0.02)

        if rel_count > 0:
            confidence += min(0.2, rel_count * 0.01)

        if context.total_tokens < 500:
            confidence -= 0.2

        return min(1.0, max(0.0, confidence))

    async def search_batch(
        self,
        queries: list[str],
        max_tokens: int | None = None,
    ) -> list[SearchResult]:
        """Perform multiple local searches in parallel.

        Args:
            queries: List of search queries.
            max_tokens: Maximum tokens per context.

        Returns:
            List of SearchResults.
        """
        import asyncio

        tasks = [self.search(query, max_tokens=max_tokens) for query in queries]
        return await asyncio.gather(*tasks)
