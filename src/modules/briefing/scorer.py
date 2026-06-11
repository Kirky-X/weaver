# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Briefing scorer — 5-dimension weighted scoring for article selection.

Dimensions:
  - quality (0.30): Article quality score from pipeline
  - cross_reference (0.20): How well-referenced the article is
  - novelty (0.20): Embedding distance from recent articles
  - user_preference (0.15): Category alignment with user reading history
  - composite (0.15): Combined credibility + impact score
"""

from __future__ import annotations

import math
from typing import Any

from core.observability.logging import get_logger

log = get_logger(__name__)

BRIEFING_WEIGHTS = {
    "quality": 0.30,
    "cross_reference": 0.20,
    "novelty": 0.20,
    "user_preference": 0.15,
    "composite": 0.15,
}


class BriefingScorer:
    """Score articles for briefing selection using five-dimensional weighted scoring."""

    @staticmethod
    def score(article: dict[str, Any]) -> tuple[float, dict[str, float]]:
        """Compute composite score and breakdown for an article.

        Args:
            article: Article dict with score fields.

        Returns:
            Tuple of (composite_score, score_breakdown) where breakdown
            contains each dimension's individual score.
        """
        quality = BriefingScorer._calc_quality(article)
        cross_reference = BriefingScorer._calc_cross_reference(article)
        novelty = BriefingScorer._calc_novelty(article)
        user_preference = BriefingScorer._calc_user_preference(article)
        composite = BriefingScorer._calc_composite(article)

        breakdown = {
            "quality": quality,
            "cross_reference": cross_reference,
            "novelty": novelty,
            "user_preference": user_preference,
            "composite": composite,
        }

        weighted = (
            quality * BRIEFING_WEIGHTS["quality"]
            + cross_reference * BRIEFING_WEIGHTS["cross_reference"]
            + novelty * BRIEFING_WEIGHTS["novelty"]
            + user_preference * BRIEFING_WEIGHTS["user_preference"]
            + composite * BRIEFING_WEIGHTS["composite"]
        )

        return weighted, breakdown

    @staticmethod
    def _calc_quality(article: dict[str, Any]) -> float:
        """Calculate quality dimension from article quality_score."""
        quality_score = article.get("quality_score")
        if quality_score is None:
            return 0.5
        return float(max(0.0, min(1.0, quality_score)))

    @staticmethod
    def _calc_cross_reference(article: dict[str, Any]) -> float:
        """Calculate cross-reference dimension based on reference count.

        Articles with more cross-references score higher, indicating
        they are well-sourced and connected within the knowledge graph.
        """
        reference_count = article.get("reference_count")
        if reference_count is None:
            return 0.5
        max_references = article.get("max_references", 10)
        if max_references <= 0:
            max_references = 10
        ratio = min(reference_count / max_references, 1.0)
        return float(ratio)

    @staticmethod
    def _calc_novelty(article: dict[str, Any]) -> float:
        """Calculate novelty dimension based on embedding distance.

        Articles whose embeddings are distant from recent articles
        are considered more novel. Uses cosine distance to measure
        how different an article is from recently seen content.

        Args:
            article: Article dict with 'embedding' and 'recent_embeddings' fields.

        Returns:
            Novelty score in [0, 1]. Higher = more novel.
        """
        embedding = article.get("embedding")
        recent_embeddings = article.get("recent_embeddings")

        if embedding is None or recent_embeddings is None or len(recent_embeddings) == 0:
            return 0.5

        # Calculate average cosine distance from recent embeddings
        distances = []
        for recent in recent_embeddings:
            if len(recent) != len(embedding):
                continue
            dist = BriefingScorer._cosine_distance(embedding, recent)
            distances.append(dist)

        if not distances:
            return 0.5

        avg_distance = sum(distances) / len(distances)
        # Cosine distance is in [0, 2], normalize to [0, 1]
        # Distance 0 = identical, 1 = orthogonal, 2 = opposite
        # Map: 0 → 0.0 (not novel), 1 → 0.5, 2 → 1.0 (very novel)
        novelty = min(avg_distance / 2.0, 1.0)
        return float(max(0.0, min(1.0, novelty)))

    @staticmethod
    def _calc_user_preference(article: dict[str, Any]) -> float:
        """Calculate user preference dimension based on category history.

        Articles in categories the user frequently reads score higher.

        Args:
            article: Article dict with 'category' and 'category_history' fields.
                category_history maps category names to read counts.

        Returns:
            Preference score in [0, 1]. Higher = more preferred category.
        """
        category = article.get("category")
        category_history = article.get("category_history")

        if not category or not category_history:
            return 0.5

        if not isinstance(category_history, dict) or len(category_history) == 0:
            return 0.5

        total_reads = sum(category_history.values())
        if total_reads == 0:
            return 0.5

        category_reads = category_history.get(category, 0)
        preference = category_reads / total_reads
        return float(max(0.0, min(1.0, preference)))

    @staticmethod
    def _calc_composite(article: dict[str, Any]) -> float:
        """Calculate composite dimension from credibility and impact scores.

        Combines the article's credibility_score and impact score (stored
        as 'score') into a single metric representing overall reliability
        and significance.

        Returns:
            Composite score in [0, 1].
        """
        credibility = article.get("credibility_score")
        impact = article.get("score")

        if credibility is None and impact is None:
            return 0.5

        credibility = float(credibility) if credibility is not None else 0.5
        impact = float(impact) if impact is not None else 0.5

        composite = (credibility + impact) / 2.0
        return float(max(0.0, min(1.0, composite)))

    @staticmethod
    def _cosine_distance(a: list[float], b: list[float]) -> float:
        """Calculate cosine distance between two vectors.

        Cosine distance = 1 - cosine_similarity.
        Returns value in [0, 2].
        """
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 1.0  # orthogonal by convention

        similarity = dot_product / (norm_a * norm_b)
        # Clamp to [-1, 1] for numerical stability
        similarity = max(-1.0, min(1.0, similarity))
        return 1.0 - similarity
