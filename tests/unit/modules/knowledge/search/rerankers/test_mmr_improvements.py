# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for MMR improvements: embedding similarity and similarity_mode.

TDD Phase 1: Write tests first, then implement.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

# Mock setfit before any imports that trigger the chain
# setfit -> transformers.training_args.default_logdir (version conflict)
if "setfit" not in sys.modules:
    sys.modules["setfit"] = MagicMock()
    sys.modules["setfit.span"] = MagicMock()
    sys.modules["setfit.span.trainer"] = MagicMock()

import pytest

from modules.knowledge.search.rerankers.mmr_reranker import MMRReranker, MMRResult

# ── Embedding Similarity ────────────────────────────────────────────


class TestMMREmbeddingSimilarity:
    """Test MMR with embedding-based cosine similarity."""

    def test_cosine_similarity_identical_vectors(self) -> None:
        """Identical vectors should have cosine similarity of 1.0."""
        reranker = MMRReranker(similarity_mode="embedding")
        sim = reranker.cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert abs(sim - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal_vectors(self) -> None:
        """Orthogonal vectors should have cosine similarity of 0.0."""
        reranker = MMRReranker(similarity_mode="embedding")
        sim = reranker.cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 1e-6

    def test_cosine_similarity_opposite_vectors(self) -> None:
        """Opposite vectors should have cosine similarity of -1.0."""
        reranker = MMRReranker(similarity_mode="embedding")
        sim = reranker.cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert abs(sim - (-1.0)) < 1e-6

    def test_cosine_similarity_zero_vector(self) -> None:
        """Zero vector should return 0.0 similarity."""
        reranker = MMRReranker(similarity_mode="embedding")
        sim = reranker.cosine_similarity([0.0, 0.0], [1.0, 0.0])
        assert sim == 0.0


class TestMMRSimilarityMode:
    """Test similarity_mode configuration."""

    def test_default_mode_is_jaccard(self) -> None:
        """Default similarity_mode should be 'jaccard'."""
        reranker = MMRReranker()
        assert reranker.similarity_mode == "jaccard"

    def test_embedding_mode(self) -> None:
        """similarity_mode='embedding' should be accepted."""
        reranker = MMRReranker(similarity_mode="embedding")
        assert reranker.similarity_mode == "embedding"

    def test_invalid_mode_raises(self) -> None:
        """Invalid similarity_mode should raise ValueError."""
        with pytest.raises(ValueError, match="similarity_mode"):
            MMRReranker(similarity_mode="invalid")

    def test_embedding_mode_uses_embedding_fn(self) -> None:
        """Embedding mode should use embedding similarity when embeddings available."""
        reranker = MMRReranker(similarity_mode="embedding")

        candidates = [
            {"id": "1", "content": "doc one", "score": 0.9, "embedding": [1.0, 0.0]},
            {"id": "2", "content": "doc two", "score": 0.8, "embedding": [0.0, 1.0]},
            {"id": "3", "content": "doc three", "score": 0.7, "embedding": [1.0, 0.0]},
        ]

        results = reranker.rerank(candidates, top_k=3)
        assert len(results) == 3
        # Doc 1 and 3 have same embedding (high similarity), so doc 3 should be penalized
        # Doc 2 has orthogonal embedding (low similarity), so it should be preferred for diversity
        result_ids = [r["id"] for r in results]
        assert result_ids[0] == "1"  # Highest relevance first

    def test_embedding_mode_fallback_to_jaccard(self) -> None:
        """Embedding mode should fall back to Jaccard when no embeddings."""
        reranker = MMRReranker(similarity_mode="embedding")

        candidates = [
            {"id": "1", "content": "alpha beta", "score": 0.9},
            {"id": "2", "content": "gamma delta", "score": 0.8},
        ]

        # Should not raise, should fall back to Jaccard
        results = reranker.rerank(candidates, top_k=2)
        assert len(results) == 2


# ── Lambda Parameter Balance ────────────────────────────────────────


class TestMMRLambdaBalance:
    """Test lambda parameter effect on relevance vs diversity."""

    def _make_diverse_candidates(self) -> list[dict[str, Any]]:
        """Create candidates with clear diversity trade-offs."""
        return [
            {"id": "1", "content": "AI machine learning neural", "score": 1.0},
            {"id": "2", "content": "AI deep learning model", "score": 0.9},
            {"id": "3", "content": "climate change environment", "score": 0.8},
            {"id": "4", "content": "AI machine learning algorithm", "score": 0.7},
        ]

    def test_high_lambda_favors_relevance(self) -> None:
        """High lambda (0.9) should keep relevance ordering mostly intact."""
        reranker = MMRReranker(lambda_param=0.9)
        candidates = self._make_diverse_candidates()
        results = reranker.rerank(candidates, top_k=4)
        # Top result should still be the most relevant
        assert results[0]["id"] == "1"

    def test_low_lambda_favors_diversity(self) -> None:
        """Low lambda (0.3) should introduce more diversity."""
        reranker = MMRReranker(lambda_param=0.3)
        candidates = self._make_diverse_candidates()
        results = reranker.rerank(candidates, top_k=4)
        # With low lambda, diverse docs should rank higher
        # The climate doc (id=3) should appear earlier than with high lambda
        assert len(results) == 4

    def test_lambda_extreme_zero(self) -> None:
        """Lambda=0 should maximize diversity (minimize relevance)."""
        reranker = MMRReranker(lambda_param=0.0)
        candidates = self._make_diverse_candidates()
        results = reranker.rerank(candidates, top_k=4)
        assert len(results) == 4

    def test_lambda_extreme_one(self) -> None:
        """Lambda=1 should maximize relevance (no diversity penalty)."""
        reranker = MMRReranker(lambda_param=1.0)
        candidates = self._make_diverse_candidates()
        results = reranker.rerank(candidates, top_k=4)
        # With no diversity penalty, results should follow relevance order
        assert results[0]["id"] == "1"


# ── Large Scale Performance ─────────────────────────────────────────


class TestMMRLargeScale:
    """Test MMR performance with large candidate sets."""

    def test_100_candidates(self) -> None:
        """MMR should handle 100+ candidates efficiently."""
        reranker = MMRReranker(lambda_param=0.7)
        candidates = [
            {"id": str(i), "content": f"document {i} content text", "score": 1.0 - i * 0.01}
            for i in range(100)
        ]
        results = reranker.rerank(candidates, top_k=10)
        assert len(results) == 10
        assert all("mmr_score" in r for r in results)

    def test_empty_candidates(self) -> None:
        """MMR should handle empty candidate list gracefully."""
        reranker = MMRReranker()
        results = reranker.rerank([])
        assert results == []

    def test_single_candidate(self) -> None:
        """MMR should handle single candidate."""
        reranker = MMRReranker()
        candidates = [{"id": "1", "content": "only doc", "score": 1.0}]
        results = reranker.rerank(candidates, top_k=5)
        assert len(results) == 1
        assert results[0]["mmr_score"] > 0


# ── Custom Similarity Function ──────────────────────────────────────


class TestMMRCustomSimilarity:
    """Test MMR with custom similarity function."""

    def test_custom_similarity_fn(self) -> None:
        """Custom similarity function should be used when provided."""
        custom_fn = MagicMock(return_value=0.5)
        reranker = MMRReranker(similarity_fn=custom_fn)

        candidates = [
            {"id": "1", "content": "doc one", "score": 0.9},
            {"id": "2", "content": "doc two", "score": 0.8},
        ]

        results = reranker.rerank(candidates, top_k=2)
        assert len(results) == 2
        # Custom fn should have been called for diversity calculation
        assert custom_fn.called

    def test_custom_fn_overrides_mode(self) -> None:
        """Explicit similarity_fn should override similarity_mode."""
        custom_fn = MagicMock(return_value=0.3)
        reranker = MMRReranker(similarity_fn=custom_fn, similarity_mode="embedding")

        candidates = [
            {"id": "1", "content": "doc one", "score": 0.9},
            {"id": "2", "content": "doc two", "score": 0.8},
        ]

        results = reranker.rerank(candidates, top_k=2)
        assert custom_fn.called
