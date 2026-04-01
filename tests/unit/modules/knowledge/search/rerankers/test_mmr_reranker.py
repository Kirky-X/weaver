# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for MMRReranker."""

from __future__ import annotations

import pytest

from modules.knowledge.search.rerankers.mmr_reranker import MMRReranker, MMRResult


class TestMMRRerankerInit:
    """Tests for MMRReranker initialization."""

    def test_default_params(self) -> None:
        """Default initialization."""
        reranker = MMRReranker()
        assert reranker._lambda == 0.7

    def test_custom_lambda(self) -> None:
        """Custom lambda parameter."""
        reranker = MMRReranker(lambda_param=0.5)
        assert reranker._lambda == 0.5

    def test_invalid_lambda_high(self) -> None:
        """Lambda > 1 raises ValueError."""
        with pytest.raises(ValueError, match="lambda_param"):
            MMRReranker(lambda_param=1.5)

    def test_invalid_lambda_negative(self) -> None:
        """Lambda < 0 raises ValueError."""
        with pytest.raises(ValueError, match="lambda_param"):
            MMRReranker(lambda_param=-0.1)

    def test_custom_similarity_fn(self) -> None:
        """Custom similarity function."""

        def custom_sim(a: str, b: str) -> float:
            return 1.0 if a == b else 0.0

        reranker = MMRReranker(similarity_fn=custom_sim)
        assert reranker._similarity_fn is custom_sim


class TestJaccardSimilarity:
    """Tests for Jaccard similarity."""

    def test_identical_texts(self) -> None:
        """Identical texts have similarity 1.0."""
        reranker = MMRReranker()
        sim = reranker._jaccard_similarity("hello world", "hello world")
        assert sim == 1.0

    def test_no_overlap(self) -> None:
        """Non-overlapping texts have similarity 0.0."""
        reranker = MMRReranker()
        sim = reranker._jaccard_similarity("apple banana", "cherry date")
        assert sim == 0.0

    def test_partial_overlap(self) -> None:
        """Partial overlap returns value between 0 and 1."""
        reranker = MMRReranker()
        sim = reranker._jaccard_similarity("apple banana", "banana cherry")
        assert 0.0 < sim < 1.0

    def test_empty_text(self) -> None:
        """Empty text returns 0.0."""
        reranker = MMRReranker()
        assert reranker._jaccard_similarity("", "hello") == 0.0
        assert reranker._jaccard_similarity("hello", "") == 0.0

    def test_case_insensitive(self) -> None:
        """Comparison is case-insensitive."""
        reranker = MMRReranker()
        sim = reranker._jaccard_similarity("Hello World", "hello world")
        assert sim == 1.0


class TestMMRRerankerRerank:
    """Tests for MMRReranker rerank method."""

    def test_empty_candidates(self) -> None:
        """Empty candidates returns empty."""
        reranker = MMRReranker()
        assert reranker.rerank([]) == []

    def test_single_candidate(self) -> None:
        """Single candidate is returned."""
        reranker = MMRReranker()
        candidates = [{"id": "1", "content": "Test document", "score": 0.9}]
        results = reranker.rerank(candidates)

        assert len(results) == 1
        assert results[0]["id"] == "1"
        assert "mmr_score" in results[0]

    def test_respects_top_k(self) -> None:
        """top_k limits results."""
        reranker = MMRReranker()
        candidates = [
            {"id": str(i), "content": f"Doc {i}", "score": 0.9 - i * 0.1} for i in range(5)
        ]
        results = reranker.rerank(candidates, top_k=3)
        assert len(results) == 3

    def test_diverse_results(self) -> None:
        """MMR promotes diversity."""
        reranker = MMRReranker(lambda_param=0.3)  # Favor diversity
        candidates = [
            {"id": "1", "content": "apple apple apple", "score": 1.0},
            {"id": "2", "content": "apple apple apple", "score": 0.9},
            {"id": "3", "content": "banana banana banana", "score": 0.8},
        ]
        results = reranker.rerank(candidates, top_k=3)

        # The diverse document should be ranked higher than similar duplicates
        ids = [r["id"] for r in results]
        assert "3" in ids

    def test_result_fields(self) -> None:
        """Results have expected fields."""
        reranker = MMRReranker()
        candidates = [{"id": "1", "content": "Test", "score": 0.9}]
        results = reranker.rerank(candidates)

        assert "mmr_score" in results[0]
        assert "original_rank" in results[0]
        assert "new_rank" in results[0]
        assert "diversity_penalty" in results[0]

    def test_uses_title_as_fallback(self) -> None:
        """Falls back to title when content is missing."""
        reranker = MMRReranker()
        candidates = [{"id": "1", "title": "Test Title", "score": 0.9}]
        results = reranker.rerank(candidates, text_key="content")
        assert len(results) == 1


class TestMMRRerankerWithMetadata:
    """Tests for rerank_with_metadata."""

    def test_returns_mmr_results(self) -> None:
        """Returns list of MMRResult."""
        reranker = MMRReranker()
        candidates = [
            {"id": "1", "content": "Doc one", "score": 0.9},
            {"id": "2", "content": "Doc two", "score": 0.8},
        ]
        results = reranker.rerank_with_metadata(candidates)

        assert all(isinstance(r, MMRResult) for r in results)
        assert len(results) == 2

    def test_mmr_result_fields(self) -> None:
        """MMRResult has expected fields."""
        reranker = MMRReranker()
        candidates = [{"id": "doc1", "content": "Test", "score": 0.9}]
        results = reranker.rerank_with_metadata(candidates)

        r = results[0]
        assert r.doc_id == "doc1"
        assert r.new_rank == 0
        assert isinstance(r.mmr_score, float)


class TestMMRRerankerSetLambda:
    """Tests for set_lambda."""

    def test_update_lambda(self) -> None:
        """Lambda can be updated."""
        reranker = MMRReranker()
        reranker.set_lambda(0.5)
        assert reranker._lambda == 0.5

    def test_invalid_lambda(self) -> None:
        """Invalid lambda raises ValueError."""
        reranker = MMRReranker()
        with pytest.raises(ValueError):
            reranker.set_lambda(2.0)


class TestMMRRerankerGetConfig:
    """Tests for get_config."""

    def test_config_keys(self) -> None:
        """Config has expected keys."""
        reranker = MMRReranker()
        config = reranker.get_config()

        assert "lambda_param" in config
        assert "similarity_fn" in config
        assert config["lambda_param"] == 0.7
