# Copyright (c) 2026 KirkyX. All Rights Reserved
"""MMR (Maximal Marginal Relevance) reranker for diversity.

MMR balances relevance and diversity in search results by selecting
documents that are both relevant to the query and diverse from
already-selected documents.

MMR formula:
    MMR = λ * Sim(d, q) - (1-λ) * max[Sim(d, d') for d' in S]

where:
- d: candidate document
- q: query
- S: set of already selected documents
- λ: trade-off parameter (0-1)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.observability.logging import get_logger

log = get_logger("mmr_reranker")


@dataclass
class MMRResult:
    """Result from MMR re-ranking."""

    doc_id: str
    mmr_score: float
    relevance_score: float
    diversity_penalty: float
    original_rank: int
    new_rank: int
    metadata: dict[str, Any] = field(default_factory=dict)


class MMRReranker:
    """MMR-based diversity reranker.

    Selects documents that maximize relevance while maintaining diversity.
    Uses text similarity (Jaccard or embedding-based) for diversity calculation.

    Args:
        lambda_param: Trade-off between relevance and diversity (0-1).
            Higher values favor relevance, lower values favor diversity.
        similarity_fn: Function to compute similarity between texts.
            If None, uses Jaccard similarity.
    """

    def __init__(
        self,
        lambda_param: float = 0.7,
        similarity_fn: Callable[[str, str], float] | None = None,
    ) -> None:
        """Initialize MMR reranker.

        Args:
            lambda_param: Relevance-diversity trade-off (default 0.7).
            similarity_fn: Optional custom similarity function.
        """
        if not 0 <= lambda_param <= 1:
            raise ValueError(f"lambda_param must be between 0 and 1, got {lambda_param}")

        self._lambda = lambda_param
        self._similarity_fn = similarity_fn or self._jaccard_similarity

        log.info("mmr_reranker_initialized", lambda_param=lambda_param)

    def _jaccard_similarity(self, text1: str, text2: str) -> float:
        """Calculate Jaccard similarity between two texts.

        Args:
            text1: First text.
            text2: Second text.

        Returns:
            Jaccard similarity score (0-1).
        """
        if not text1 or not text2:
            return 0.0

        # Tokenize by whitespace (simple approach)
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    def rerank(
        self,
        candidates: list[dict[str, Any]],
        query: str | None = None,
        top_k: int | None = None,
        text_key: str = "content",
    ) -> list[dict[str, Any]]:
        """Re-rank candidates using MMR for diversity.

        Args:
            candidates: List of candidate documents with relevance scores.
            query: Optional query text for relevance calculation.
            top_k: Number of results to return.
            text_key: Key to use for text content.

        Returns:
            Re-ranked candidates with MMR scores.
        """
        if not candidates:
            return []

        top_k = top_k or len(candidates)
        n_candidates = len(candidates)

        # Extract texts and scores
        texts = [c.get(text_key, c.get("title", "")) for c in candidates]
        relevance_scores = [c.get("score", c.get("rerank_score", 1.0)) for c in candidates]

        # Normalize relevance scores to 0-1
        max_score = max(relevance_scores) if relevance_scores else 1.0
        if max_score > 0:
            relevance_scores = [s / max_score for s in relevance_scores]

        # Greedy MMR selection
        selected_indices: list[int] = []
        selected_texts: list[str] = []
        mmr_scores: list[float] = []

        remaining = set(range(n_candidates))

        while remaining and len(selected_indices) < top_k:
            best_idx = -1
            best_mmr = float("-inf")
            best_penalty = 0.0

            for idx in remaining:
                # Relevance component
                relevance = relevance_scores[idx]

                # Diversity penalty
                if selected_texts:
                    text = texts[idx]
                    max_sim = max(
                        self._similarity_fn(text, sel_text) for sel_text in selected_texts
                    )
                    penalty = max_sim
                else:
                    penalty = 0.0

                # MMR score
                mmr = self._lambda * relevance - (1 - self._lambda) * penalty

                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = idx
                    best_penalty = penalty

            if best_idx >= 0:
                selected_indices.append(best_idx)
                selected_texts.append(texts[best_idx])
                mmr_scores.append(best_mmr)
                remaining.remove(best_idx)

        # Build output
        results = []
        for new_rank, idx in enumerate(selected_indices):
            result = candidates[idx].copy()
            result["mmr_score"] = mmr_scores[new_rank]
            result["original_rank"] = idx
            result["new_rank"] = new_rank
            result["diversity_penalty"] = (
                (relevance_scores[idx] - mmr_scores[new_rank]) / (1 - self._lambda)
                if self._lambda < 1
                else 0
            )
            results.append(result)

        log.debug(
            "mmr_rerank_complete",
            candidates=len(candidates),
            returned=len(results),
            lambda_param=self._lambda,
        )

        return results

    def rerank_with_metadata(
        self,
        candidates: list[dict[str, Any]],
        query: str | None = None,
        top_k: int | None = None,
    ) -> list[MMRResult]:
        """Re-rank and return structured results.

        Args:
            candidates: List of candidate documents.
            query: Optional query text.
            top_k: Number of results to return.

        Returns:
            List of MMRResult objects.
        """
        ranked = self.rerank(candidates, query, top_k)

        return [
            MMRResult(
                doc_id=item.get("id", str(i)),
                mmr_score=item.get("mmr_score", 0.0),
                relevance_score=item.get("score", item.get("rerank_score", 0.0)),
                diversity_penalty=item.get("diversity_penalty", 0.0),
                original_rank=item.get("original_rank", i),
                new_rank=i,
                metadata=item,
            )
            for i, item in enumerate(ranked)
        ]

    def set_lambda(self, lambda_param: float) -> None:
        """Set the lambda parameter.

        Args:
            lambda_param: New lambda value (0-1).
        """
        if not 0 <= lambda_param <= 1:
            raise ValueError(f"lambda_param must be between 0 and 1, got {lambda_param}")
        self._lambda = lambda_param
        log.info("mmr_lambda_updated", lambda_param=lambda_param)

    def get_config(self) -> dict[str, Any]:
        """Get current configuration."""
        return {
            "lambda_param": self._lambda,
            "similarity_fn": self._similarity_fn.__name__,
        }
