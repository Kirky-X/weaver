# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Reciprocal Rank Fusion (RRF) algorithm for combining multiple retrieval results.

RRF is a simple yet effective method for combining ranked lists from multiple
retrieval systems without requiring score normalization.

RRF formula:
    RRF_score(d) = Σ (1 / (k + rank_i(d)))

where k is a constant (default: 60) and rank_i(d) is the rank of document d
in the i-th ranked list.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from core.observability.logging import get_logger

log = get_logger("rrf_fusion")

T = TypeVar("T")


@dataclass
class RRFResult(Generic[T]):
    """Result from RRF fusion."""

    item: T
    rrf_score: float
    ranks: list[int] = field(default_factory=list)
    original_scores: list[float] = field(default_factory=list)


def reciprocal_rank_fusion(
    results_list: list[list[tuple[Any, float]]],
    k: int = 60,
    return_scores: bool = True,
) -> list[tuple[Any, float]]:
    """Combine multiple ranked lists using Reciprocal Rank Fusion.

    Args:
        results_list: List of ranked lists, each containing (item, score) tuples.
        k: RRF constant for rank smoothing (default: 60).
        return_scores: Whether to return RRF scores or just items.

    Returns:
        Fused list of (item, rrf_score) tuples sorted by RRF score.

    Example:
        >>> vector_results = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        >>> bm25_results = [("doc2", 15.0), ("doc4", 12.0), ("doc1", 10.0)]
        >>> fused = reciprocal_rank_fusion([vector_results, bm25_results])
        >>> # Returns combined results sorted by RRF score
    """
    if not results_list:
        return []

    # Track RRF scores and ranks for each unique item
    item_scores: dict[Any, float] = defaultdict(float)
    item_ranks: dict[Any, list[int]] = defaultdict(list)

    for ranked_list in results_list:
        for rank, (item, _) in enumerate(ranked_list, start=1):
            rrf_contribution = 1.0 / (k + rank)
            item_scores[item] += rrf_contribution
            item_ranks[item].append(rank)

    # Sort by RRF score (descending)
    sorted_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)

    log.debug(
        "rrf_fusion_complete",
        num_lists=len(results_list),
        total_items=len(item_scores),
        top_score=sorted_items[0][1] if sorted_items else 0,
    )

    if return_scores:
        return sorted_items
    return [(item, score) for item, score in sorted_items]


def reciprocal_rank_fusion_with_metadata(
    results_list: list[list[tuple[Any, float]]],
    k: int = 60,
) -> list[RRFResult[Any]]:
    """Combine ranked lists with full metadata.

    Args:
        results_list: List of ranked lists, each containing (item, score) tuples.
        k: RRF constant for rank smoothing.

    Returns:
        List of RRFResult objects with full metadata.
    """
    if not results_list:
        return []

    # Track all metadata
    item_data: dict[Any, dict[str, Any]] = defaultdict(
        lambda: {"rrf_score": 0.0, "ranks": [], "scores": []}
    )

    for ranked_list in results_list:
        for rank, (item, score) in enumerate(ranked_list, start=1):
            rrf_contribution = 1.0 / (k + rank)
            item_data[item]["rrf_score"] += rrf_contribution
            item_data[item]["ranks"].append(rank)
            item_data[item]["scores"].append(score)

    # Build results
    results = [
        RRFResult(
            item=item,
            rrf_score=data["rrf_score"],
            ranks=data["ranks"],
            original_scores=data["scores"],
        )
        for item, data in item_data.items()
    ]

    # Sort by RRF score
    results.sort(key=lambda x: x.rrf_score, reverse=True)

    return results


def weighted_rrf(
    results_list: list[list[tuple[Any, float]]],
    weights: list[float] | None = None,
    k: int = 60,
) -> list[tuple[Any, float]]:
    """Weighted Reciprocal Rank Fusion.

    Applies weights to different retrieval systems before fusion.

    Args:
        results_list: List of ranked lists.
        weights: Weight for each retrieval system. Must match length of results_list.
        k: RRF constant.

    Returns:
        Fused and weighted results.

    Raises:
        ValueError: If weights length doesn't match results_list length.
    """
    if not results_list:
        return []

    if weights is None:
        # Equal weights
        weights = [1.0] * len(results_list)

    if len(weights) != len(results_list):
        raise ValueError(
            f"Weights length ({len(weights)}) must match results_list length ({len(results_list)})"
        )

    # Normalize weights
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]

    # Track RRF scores
    item_scores: dict[Any, float] = defaultdict(float)

    for ranked_list, weight in zip(results_list, weights):
        for rank, (item, _) in enumerate(ranked_list, start=1):
            rrf_contribution = weight / (k + rank)
            item_scores[item] += rrf_contribution

    # Sort by RRF score
    sorted_items = sorted(item_scores.items(), key=lambda x: x[1], reverse=True)

    return sorted_items


def fusion_score_at_k(
    results_list: list[list[tuple[Any, float]]],
    k: int = 60,
    top_k: int = 10,
) -> dict[str, float]:
    """Calculate fusion quality metrics.

    Args:
        results_list: List of ranked lists.
        k: RRF constant.
        top_k: Number of top results to consider.

    Returns:
        Dictionary of quality metrics.
    """
    fused = reciprocal_rank_fusion(results_list, k=k)

    if not fused:
        return {"precision_at_k": 0.0, "num_unique_items": 0}

    # Calculate overlap between sources
    all_items = set()
    for ranked_list in results_list[:top_k]:
        for item, _ in ranked_list[:top_k]:
            all_items.add(item)

    return {
        "precision_at_k": len(fused[:top_k]) / top_k if top_k > 0 else 0.0,
        "num_unique_items": len(all_items),
        "num_fused_items": len(fused),
    }
