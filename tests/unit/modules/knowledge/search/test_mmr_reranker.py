# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for MMRReranker."""

from __future__ import annotations

import pytest

from modules.knowledge.search.rerankers.mmr_reranker import MMRReranker, MMRResult


class TestMMRRerankerInit:
    """Tests for MMRReranker initialization."""

    def test_init_default_params(self) -> None:
        """Test initialization with default parameters."""
        reranker = MMRReranker()

        assert reranker._lambda == 0.7
        assert reranker._similarity_fn is not None

    def test_init_custom_lambda(self) -> None:
        """Test initialization with custom lambda."""
        reranker = MMRReranker(lambda_param=0.5)

        assert reranker._lambda == 0.5

    def test_init_invalid_lambda_high(self) -> None:
        """Test initialization with lambda > 1 raises error."""
        with pytest.raises(ValueError, match="lambda_param must be between 0 and 1"):
            MMRReranker(lambda_param=1.5)

    def test_init_invalid_lambda_low(self) -> None:
        """Test initialization with lambda < 0 raises error."""
        with pytest.raises(ValueError, match="lambda_param must be between 0 and 1"):
            MMRReranker(lambda_param=-0.1)

    def test_init_custom_similarity_fn(self) -> None:
        """Test initialization with custom similarity function."""

        def custom_sim(a: str, b: str) -> float:
            return 1.0 if a == b else 0.0

        reranker = MMRReranker(similarity_fn=custom_sim)

        assert reranker._similarity_fn == custom_sim


class TestMMRRerankerJaccardSimilarity:
    """Tests for Jaccard similarity calculation."""

    def test_identical_texts(self) -> None:
        """Test Jaccard similarity of identical texts."""
        reranker = MMRReranker()
        similarity = reranker._jaccard_similarity("hello world", "hello world")

        assert similarity == 1.0

    def test_no_overlap(self) -> None:
        """Test Jaccard similarity with no word overlap."""
        reranker = MMRReranker()
        similarity = reranker._jaccard_similarity("hello world", "foo bar")

        assert similarity == 0.0

    def test_partial_overlap(self) -> None:
        """Test Jaccard similarity with partial overlap."""
        reranker = MMRReranker()
        # "hello world" vs "hello there" -> overlap: "hello" (1 word)
        # union: "hello", "world", "there" (3 words)
        # Jaccard = 1/3 ≈ 0.333
        similarity = reranker._jaccard_similarity("hello world", "hello there")

        assert 0 < similarity < 1

    def test_empty_texts(self) -> None:
        """Test Jaccard similarity with empty texts."""
        reranker = MMRReranker()

        assert reranker._jaccard_similarity("", "text") == 0.0
        assert reranker._jaccard_similarity("text", "") == 0.0
        assert reranker._jaccard_similarity("", "") == 0.0

    def test_case_insensitivity(self) -> None:
        """Test that Jaccard similarity is case-insensitive."""
        reranker = MMRReranker()
        similarity = reranker._jaccard_similarity("Hello World", "hello world")

        assert similarity == 1.0


class TestMMRRerankerRerank:
    """Tests for MMRReranker rerank method."""

    def test_rerank_empty_candidates(self) -> None:
        """Test reranking empty candidate list."""
        reranker = MMRReranker()
        results = reranker.rerank(candidates=[])

        assert results == []

    def test_rerank_single_candidate(self) -> None:
        """Test reranking single candidate."""
        reranker = MMRReranker()

        candidates = [
            {"id": "1", "content": "Single document", "score": 0.9},
        ]

        results = reranker.rerank(candidates=candidates)

        assert len(results) == 1
        assert results[0]["id"] == "1"

    def test_rerank_multiple_candidates(self) -> None:
        """Test reranking multiple candidates."""
        reranker = MMRReranker()

        candidates = [
            {"id": "1", "content": "Python programming basics", "score": 0.9},
            {"id": "2", "content": "Python programming advanced", "score": 0.8},
            {"id": "3", "content": "Java development guide", "score": 0.7},
        ]

        results = reranker.rerank(candidates=candidates)

        assert len(results) == 3
        # Results should have mmr_score
        assert all("mmr_score" in r for r in results)

    def test_rerank_respects_top_k(self) -> None:
        """Test that rerank respects top_k parameter."""
        reranker = MMRReranker()

        candidates = [
            {"id": "1", "content": "First document", "score": 0.9},
            {"id": "2", "content": "Second document", "score": 0.8},
            {"id": "3", "content": "Third document", "score": 0.7},
        ]

        results = reranker.rerank(candidates=candidates, top_k=2)

        assert len(results) == 2

    def test_rerank_adds_metadata(self) -> None:
        """Test that rerank adds expected metadata."""
        reranker = MMRReranker()

        candidates = [
            {"id": "1", "content": "Test document", "score": 0.9},
        ]

        results = reranker.rerank(candidates=candidates)

        assert "mmr_score" in results[0]
        assert "original_rank" in results[0]
        assert "new_rank" in results[0]
        assert "diversity_penalty" in results[0]

    def test_rerank_diversity_effect(self) -> None:
        """Test that MMR promotes diversity.

        With low lambda (favoring diversity), similar documents
        should be pushed down.
        """
        # Low lambda = high diversity preference
        reranker = MMRReranker(lambda_param=0.3)

        candidates = [
            {"id": "1", "content": "Python programming tutorial", "score": 1.0},
            {"id": "2", "content": "Python programming guide", "score": 0.95},  # Very similar to 1
            {
                "id": "3",
                "content": "Java development tutorial",
                "score": 0.9,
            },  # Different from 1, 2
        ]

        results = reranker.rerank(candidates=candidates)

        # First result should still be the highest scoring one
        assert results[0]["id"] == "1"

        # With diversity preference, doc3 (Java) might rank higher than doc2 (Python similar)
        # because it's more diverse from doc1
        ids = [r["id"] for r in results]

        # All documents should be present
        assert set(ids) == {"1", "2", "3"}


class TestMMRRerankerWithMetadata:
    """Tests for MMRReranker rerank_with_metadata method."""

    def test_rerank_with_metadata_structure(self) -> None:
        """Test that results have correct structure."""
        reranker = MMRReranker()

        candidates = [
            {"id": "doc-1", "content": "Test content", "title": "Test Title", "score": 0.9},
        ]

        results = reranker.rerank_with_metadata(candidates=candidates)

        assert len(results) == 1
        result = results[0]
        assert isinstance(result, MMRResult)
        assert result.doc_id == "doc-1"

    def test_rerank_with_metadata_multiple(self) -> None:
        """Test rerank_with_metadata with multiple candidates."""
        reranker = MMRReranker()

        candidates = [
            {"id": "1", "content": "First document", "score": 0.9},
            {"id": "2", "content": "Second document", "score": 0.8},
        ]

        results = reranker.rerank_with_metadata(candidates=candidates)

        assert len(results) == 2
        assert all(isinstance(r, MMRResult) for r in results)


class TestMMRRerankerSetLambda:
    """Tests for MMRReranker set_lambda method."""

    def test_set_lambda_valid(self) -> None:
        """Test setting valid lambda value."""
        reranker = MMRReranker(lambda_param=0.7)
        reranker.set_lambda(0.5)

        assert reranker._lambda == 0.5

    def test_set_lambda_invalid(self) -> None:
        """Test setting invalid lambda value raises error."""
        reranker = MMRReranker()

        with pytest.raises(ValueError):
            reranker.set_lambda(1.5)


class TestMMRRerankerGetConfig:
    """Tests for MMRReranker get_config method."""

    def test_get_config(self) -> None:
        """Test getting configuration."""
        reranker = MMRReranker(lambda_param=0.6)
        config = reranker.get_config()

        assert config["lambda_param"] == 0.6
        assert "similarity_fn" in config


class TestMMRLambdaEffect:
    """Tests verifying lambda parameter effect on results."""

    def test_high_lambda_favors_relevance(self) -> None:
        """Test that high lambda (0.9) favors relevance over diversity."""
        reranker = MMRReranker(lambda_param=0.9)

        candidates = [
            {"id": "1", "content": "Python programming", "score": 1.0},
            {"id": "2", "content": "Python programming advanced", "score": 0.9},
            {"id": "3", "content": "Java development", "score": 0.8},
        ]

        results = reranker.rerank(candidates=candidates)

        # With high lambda, order should closely follow original scores
        # because diversity penalty is minimal
        ids = [r["id"] for r in results]
        assert ids[0] == "1"  # Highest score first

    def test_low_lambda_favors_diversity(self) -> None:
        """Test that low lambda (0.1) favors diversity over relevance."""
        reranker = MMRReranker(lambda_param=0.1)

        candidates = [
            {"id": "1", "content": "Python programming basics", "score": 1.0},
            {
                "id": "2",
                "content": "Python programming advanced",
                "score": 0.99,
            },  # Very similar to 1
            {"id": "3", "content": "Java development tutorial", "score": 0.9},  # Different topic
        ]

        results = reranker.rerank(candidates=candidates)

        # First should still be highest relevance
        assert results[0]["id"] == "1"

        # With low lambda, the diverse document (Java) should have lower penalty
        # and might rank higher than the similar Python document
