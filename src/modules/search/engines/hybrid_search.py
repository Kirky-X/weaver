# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Hybrid search engine combining vector, BM25, and graph retrieval.

This engine implements a multi-stage retrieval pipeline:
1. Parallel retrieval from multiple sources (vector, BM25, graph)
2. RRF fusion of results
3. Optional cross-encoder re-ranking
4. Optional MMR diversity re-ranking

This approach significantly improves recall and precision over
single-source retrieval.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from core.observability.logging import get_logger
from modules.search.fusion.rrf import reciprocal_rank_fusion
from modules.search.rerankers.flashrank_reranker import FlashrankReranker
from modules.search.rerankers.mmr_reranker import MMRReranker
from modules.search.retrievers.bm25_retriever import BM25Retriever

log = get_logger("hybrid_search")


@dataclass
class HybridSearchConfig:
    """Configuration for hybrid search."""

    hybrid_enabled: bool = True
    rerank_enabled: bool = True
    rerank_model: str = "tiny"
    mmr_enabled: bool = False
    mmr_lambda: float = 0.7
    vector_weight: float = 1.0
    bm25_weight: float = 1.0
    graph_weight: float = 1.0
    rrf_k: int = 60
    top_k: int = 10


@dataclass
class HybridSearchResult:
    """Result from hybrid search."""

    doc_id: str
    score: float
    title: str
    content: str
    source: str
    vector_rank: int | None = None
    bm25_rank: int | None = None
    rerank_score: float | None = None
    mmr_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HybridSearchEngine:
    """Hybrid search engine combining multiple retrieval methods.

    Combines:
    - Vector similarity search (semantic)
    - BM25 lexical search (keyword)
    - Graph-based search (entity relationships)

    Uses Reciprocal Rank Fusion (RRF) to merge results, with optional
    cross-encoder re-ranking and MMR diversity.

    Args:
        vector_repo: Vector repository for semantic search.
        bm25_retriever: BM25 retriever for lexical search.
        reranker: Optional Flashrank reranker.
        mmr_reranker: Optional MMR diversity reranker.
        config: Hybrid search configuration.
    """

    def __init__(
        self,
        vector_repo: Any = None,
        bm25_retriever: BM25Retriever | None = None,
        reranker: FlashrankReranker | None = None,
        mmr_reranker: MMRReranker | None = None,
        config: HybridSearchConfig | None = None,
    ) -> None:
        """Initialize hybrid search engine.

        Args:
            vector_repo: Vector repository for semantic search.
            bm25_retriever: BM25 retriever for lexical search.
            reranker: Flashrank reranker instance.
            mmr_reranker: MMR reranker instance.
            config: Search configuration.
        """
        self._vector_repo = vector_repo
        self._bm25_retriever = bm25_retriever
        self._reranker = reranker
        self._mmr_reranker = mmr_reranker
        self._config = config or HybridSearchConfig()

        log.info(
            "hybrid_search_initialized",
            hybrid_enabled=self._config.hybrid_enabled,
            rerank_enabled=self._config.rerank_enabled,
            mmr_enabled=self._config.mmr_enabled,
        )

    async def search(
        self,
        query: str,
        embedding: list[float] | None = None,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[HybridSearchResult]:
        """Perform hybrid search.

        Args:
            query: Search query text.
            embedding: Pre-computed query embedding (optional).
            limit: Maximum results to return.
            filters: Optional metadata filters.

        Returns:
            List of HybridSearchResult objects.
        """
        if not self._config.hybrid_enabled:
            # Fallback to vector-only search
            return await self._vector_only_search(query, embedding, limit)

        # Stage 1: Parallel retrieval
        vector_results, bm25_results = await self._parallel_retrieve(query, embedding, limit * 2)

        # Stage 2: RRF fusion
        fused = self._fuse_results(vector_results, bm25_results)

        # Stage 3: Optional re-ranking
        if self._config.rerank_enabled and self._reranker:
            fused = self._rerank_results(query, fused)

        # Stage 4: Optional MMR diversity
        if self._config.mmr_enabled and self._mmr_reranker:
            fused = self._apply_mmr(fused)

        # Convert to output format
        results = self._to_hybrid_results(fused[:limit])

        log.debug(
            "hybrid_search_complete",
            query=query[:50],
            vector_count=len(vector_results),
            bm25_count=len(bm25_results),
            fused_count=len(fused),
            returned=len(results),
        )

        return results

    async def _parallel_retrieve(
        self,
        query: str,
        embedding: list[float] | None,
        limit: int,
    ) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        """Execute parallel retrieval from multiple sources.

        Args:
            query: Search query.
            embedding: Query embedding.
            limit: Number of results per source.

        Returns:
            Tuple of (vector_results, bm25_results).
        """
        tasks = []

        # Vector search task
        if self._vector_repo and embedding:
            tasks.append(self._vector_search(embedding, limit))
        else:
            tasks.append(self._empty_result())

        # BM25 search task
        if self._bm25_retriever:
            tasks.append(self._bm25_search(query, limit))
        else:
            tasks.append(self._empty_result())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        vector_results = results[0] if not isinstance(results[0], Exception) else []
        bm25_results = results[1] if not isinstance(results[1], Exception) else []

        if isinstance(results[0], Exception):
            log.warning("vector_search_failed", error=str(results[0]))

        if isinstance(results[1], Exception):
            log.warning("bm25_search_failed", error=str(results[1]))

        return vector_results, bm25_results

    async def _vector_search(
        self,
        embedding: list[float],
        limit: int,
    ) -> list[tuple[str, float]]:
        """Execute vector similarity search.

        Args:
            embedding: Query embedding.
            limit: Number of results.

        Returns:
            List of (doc_id, score) tuples.
        """
        if not self._vector_repo:
            return []

        try:
            results = await self._vector_repo.find_similar(embedding, limit=limit)
            return [(r.get("id", r.get("doc_id", "")), r.get("score", 0.0)) for r in results]
        except Exception as exc:
            log.error("vector_search_error", error=str(exc))
            return []

    async def _bm25_search(
        self,
        query: str,
        limit: int,
    ) -> list[tuple[str, float]]:
        """Execute BM25 lexical search.

        Args:
            query: Search query.
            limit: Number of results.

        Returns:
            List of (doc_id, score) tuples.
        """
        if not self._bm25_retriever:
            return []

        try:
            # Run BM25 in thread pool (it's synchronous)
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self._bm25_retriever.retrieve(query, top_k=limit),
            )
            return [(r.doc_id, r.score) for r in results]
        except Exception as exc:
            log.error("bm25_search_error", error=str(exc))
            return []

    async def _empty_result(self) -> list[tuple[str, float]]:
        """Return empty result for optional search."""
        return []

    def _fuse_results(
        self,
        vector_results: list[tuple[str, float]],
        bm25_results: list[tuple[str, float]],
    ) -> list[dict[str, Any]]:
        """Fuse results using Reciprocal Rank Fusion.

        Args:
            vector_results: Vector search results.
            bm25_results: BM25 search results.

        Returns:
            Fused results with RRF scores.
        """
        # Prepare results lists with weights
        results_list = []
        if vector_results:
            results_list.append(vector_results)
        if bm25_results:
            results_list.append(bm25_results)

        if not results_list:
            return []

        # Apply RRF
        fused = reciprocal_rank_fusion(
            results_list,
            k=self._config.rrf_k,
        )

        # Track source ranks
        vector_rank_map = {doc_id: rank for rank, (doc_id, _) in enumerate(vector_results, 1)}
        bm25_rank_map = {doc_id: rank for rank, (doc_id, _) in enumerate(bm25_results, 1)}

        return [
            {
                "doc_id": doc_id,
                "rrf_score": score,
                "vector_rank": vector_rank_map.get(doc_id),
                "bm25_rank": bm25_rank_map.get(doc_id),
            }
            for doc_id, score in fused
        ]

    def _rerank_results(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply cross-encoder re-ranking.

        Args:
            query: Search query.
            results: Fused results.

        Returns:
            Re-ranked results.
        """
        if not self._reranker or not results:
            return results

        # Prepare candidates
        candidates = [
            {
                "id": r["doc_id"],
                "content": r.get("content", ""),
                "title": r.get("title", ""),
                **r,
            }
            for r in results
        ]

        # Rerank
        reranked = self._reranker.rerank(query, candidates)

        # Update scores
        for r in reranked:
            r["rerank_score"] = r.get("rerank_score", 0.0)

        return reranked

    def _apply_mmr(
        self,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply MMR diversity re-ranking.

        Args:
            results: Results to diversify.

        Returns:
            Diversified results.
        """
        if not self._mmr_reranker or not results:
            return results

        return self._mmr_reranker.rerank(
            results,
            top_k=len(results),
            text_key="content",
        )

    def _to_hybrid_results(
        self,
        results: list[dict[str, Any]],
    ) -> list[HybridSearchResult]:
        """Convert to HybridSearchResult objects.

        Args:
            results: Internal result dicts.

        Returns:
            List of HybridSearchResult objects.
        """
        return [
            HybridSearchResult(
                doc_id=r.get("doc_id", ""),
                score=r.get("rerank_score", r.get("rrf_score", 0.0)),
                title=r.get("title", ""),
                content=r.get("content", ""),
                source="hybrid",
                vector_rank=r.get("vector_rank"),
                bm25_rank=r.get("bm25_rank"),
                rerank_score=r.get("rerank_score"),
                mmr_score=r.get("mmr_score"),
                metadata=r,
            )
            for r in results
        ]

    async def _vector_only_search(
        self,
        query: str,
        embedding: list[float] | None,
        limit: int,
    ) -> list[HybridSearchResult]:
        """Fallback to vector-only search.

        Args:
            query: Search query.
            embedding: Query embedding.
            limit: Result limit.

        Returns:
            Search results.
        """
        if not embedding or not self._vector_repo:
            return []

        results = await self._vector_search(embedding, limit)

        return [
            HybridSearchResult(
                doc_id=doc_id,
                score=score,
                title="",
                content="",
                source="vector",
                vector_rank=i + 1,
                metadata={"original_score": score},
            )
            for i, (doc_id, score) in enumerate(results)
        ]

    def set_config(self, config: HybridSearchConfig) -> None:
        """Update search configuration.

        Args:
            config: New configuration.
        """
        self._config = config
        log.info("hybrid_search_config_updated", config=config)

    def get_stats(self) -> dict[str, Any]:
        """Get engine statistics."""
        return {
            "hybrid_enabled": self._config.hybrid_enabled,
            "rerank_enabled": self._config.rerank_enabled,
            "mmr_enabled": self._config.mmr_enabled,
            "bm25_available": self._bm25_retriever is not None,
            "bm25_doc_count": (
                self._bm25_retriever.get_document_count() if self._bm25_retriever else 0
            ),
            "reranker_available": self._reranker.is_available() if self._reranker else False,
        }
