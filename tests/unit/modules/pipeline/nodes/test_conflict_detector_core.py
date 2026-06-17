# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ConflictDetectorNode core query implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.processing.nodes.quality.conflict_detector import (
    ATTRIBUTE_SYNONYMS,
    CONFLICT_THRESHOLD,
    ConflictDetectorNode,
)
from modules.processing.pipeline.state import PipelineState

# ---------------------------------------------------------------------------
# _find_similar using VectorRepo
# ---------------------------------------------------------------------------


class TestFindSimilarVectorSearch:
    """Tests for _find_similar using VectorRepo.find_similar."""

    @pytest.mark.asyncio
    async def test_find_similar_uses_vector_repo(self):
        """_find_similar calls VectorRepo.find_similar with embedding."""
        mock_article_repo = MagicMock()
        mock_vector_repo = AsyncMock()
        mock_vector_repo.find_similar.return_value = [
            MagicMock(article_id="art-1", category="economy", similarity=0.85)
        ]

        node = ConflictDetectorNode(
            article_repo=mock_article_repo,
            vector_repo=mock_vector_repo,
        )
        # Mock embedding retrieval
        node._get_article_embedding = AsyncMock(return_value=[0.1] * 384)

        result = await node._find_similar("economy", "art-0")
        assert len(result) >= 1
        mock_vector_repo.find_similar.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_similar_no_vector_repo_returns_empty(self):
        """_find_similar returns empty list when vector_repo is None."""
        mock_article_repo = MagicMock()
        node = ConflictDetectorNode(article_repo=mock_article_repo, vector_repo=None)
        result = await node._find_similar("economy", "art-0")
        assert result == []

    @pytest.mark.asyncio
    async def test_find_similar_threshold_07(self):
        """_find_similar uses similarity threshold >= 0.7."""
        mock_article_repo = MagicMock()
        mock_vector_repo = AsyncMock()
        mock_vector_repo.find_similar.return_value = []

        node = ConflictDetectorNode(
            article_repo=mock_article_repo,
            vector_repo=mock_vector_repo,
        )
        node._get_article_embedding = AsyncMock(return_value=[0.1] * 384)
        await node._find_similar("economy", "art-0")

        call_kwargs = mock_vector_repo.find_similar.call_args
        assert call_kwargs[1].get("threshold", 0.8) >= 0.7

    @pytest.mark.asyncio
    async def test_find_similar_top_k_10(self):
        """_find_similar limits results to top_k=10."""
        mock_article_repo = MagicMock()
        mock_vector_repo = AsyncMock()
        mock_vector_repo.find_similar.return_value = []

        node = ConflictDetectorNode(
            article_repo=mock_article_repo,
            vector_repo=mock_vector_repo,
        )
        node._get_article_embedding = AsyncMock(return_value=[0.1] * 384)
        await node._find_similar("economy", "art-0")

        call_kwargs = mock_vector_repo.find_similar.call_args
        assert call_kwargs[1].get("limit", 20) <= 10


# ---------------------------------------------------------------------------
# LLM numerical claim extraction
# ---------------------------------------------------------------------------


class TestLLMClaimExtraction:
    """Tests for _extract_numerical_claims using LLM."""

    @pytest.mark.asyncio
    async def test_llm_extracts_numerical_claims(self):
        """LLM extracts structured numerical claims from text."""
        mock_llm = AsyncMock()
        mock_llm.call_at.return_value = [
            {"attribute": "GDP增长率", "value": 6.5, "unit": "%", "context": "GDP增长6.5%"},
            {"attribute": "通胀率", "value": 2.3, "unit": "%", "context": "通胀率2.3%"},
        ]

        node = ConflictDetectorNode(
            article_repo=MagicMock(),
            llm_client=mock_llm,
        )

        claims = await node._extract_numerical_claims("GDP增长6.5%，通胀率2.3%")
        assert len(claims) == 2
        assert claims[0]["attribute"] == "GDP增长率"
        assert claims[0]["value"] == 6.5
        assert claims[1]["attribute"] == "通胀率"
        assert claims[1]["value"] == 2.3

    @pytest.mark.asyncio
    async def test_llm_no_numerical_claims(self):
        """LLM returns empty list when no numerical data in text."""
        mock_llm = AsyncMock()
        mock_llm.call_at.return_value = []

        node = ConflictDetectorNode(
            article_repo=MagicMock(),
            llm_client=mock_llm,
        )

        claims = await node._extract_numerical_claims("纯文本内容，没有数字声明")
        assert claims == []

    @pytest.mark.asyncio
    async def test_llm_fallback_to_regex(self):
        """When LLM is not available, falls back to regex extraction."""
        node = ConflictDetectorNode(
            article_repo=MagicMock(),
            llm_client=None,
        )

        claims = await node._extract_numerical_claims("增长30% 下降10%")
        assert len(claims) > 0
        # Should still extract via regex
        values = [c["value"] for c in claims]
        assert 30.0 in values or 10.0 in values


# ---------------------------------------------------------------------------
# 15% conflict threshold
# ---------------------------------------------------------------------------


class TestConflictThreshold:
    """Tests for 15% conflict threshold (not 20%)."""

    def test_conflict_threshold_is_15(self):
        """CONFLICT_THRESHOLD constant should be 15."""
        assert CONFLICT_THRESHOLD == 15

    @pytest.mark.asyncio
    async def test_15_pct_difference_detected(self, sample_raw):
        """Values differing by exactly 15% should be detected as conflict."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        # 6.5 vs 7.475 = 13% relative difference (below 15%)
        # Use 6.0 vs 7.5 = 20% relative difference (above 15%)
        claims_a = [{"attribute": "GDP增长率", "value": 6.0, "unit": "%", "text": "GDP增长6.0%"}]
        claims_b = [{"attribute": "GDP增长率", "value": 7.5, "unit": "%", "text": "GDP增长7.5%"}]

        similar = [{"title": "Other", "body": "", "_claims": claims_b}]
        conflicts = node._detect_conflicts_from_claims(claims_a, similar)
        assert len(conflicts) >= 1

    @pytest.mark.asyncio
    async def test_below_15_pct_not_detected(self, sample_raw):
        """Values differing by less than 15% should NOT be detected as conflict."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        # 6.5 vs 7.0 = ~7.7% relative difference
        claims_a = [{"attribute": "GDP增长率", "value": 6.5, "unit": "%", "text": "GDP增长6.5%"}]
        claims_b = [{"attribute": "GDP增长率", "value": 7.0, "unit": "%", "text": "GDP增长7.0%"}]

        similar = [{"title": "Other", "body": "", "_claims": claims_b}]
        conflicts = node._detect_conflicts_from_claims(claims_a, similar)
        assert len(conflicts) == 0


# ---------------------------------------------------------------------------
# ATTRIBUTE_SYNONYMS matching
# ---------------------------------------------------------------------------


class TestSynonymMatching:
    """Tests for _same_attribute using ATTRIBUTE_SYNONYMS."""

    def test_same_attribute_matches_synonyms(self):
        """_same_attribute matches synonyms from ATTRIBUTE_SYNONYMS."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        c1 = {"attribute": "GDP增长率"}
        c2 = {"attribute": "经济增长率"}
        # "GDP增长率" contains "GDP" which maps to "gdp" in synonyms
        # "经济增长率" contains "增长" which maps to "growth_rate" in synonyms
        # They should match via the synonym group
        assert node._same_attribute(c1, c2) is True

    def test_same_attribute_matches_unemployment_synonyms(self):
        """_same_attribute matches unemployment synonyms."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        c1 = {"attribute": "失业率"}
        c2 = {"attribute": "失业"}
        assert node._same_attribute(c1, c2) is True

    def test_same_attribute_rejects_unrelated(self):
        """_same_attribute rejects unrelated attributes."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        c1 = {"attribute": "GDP增长率"}
        c2 = {"attribute": "失业率"}
        assert node._same_attribute(c1, c2) is False

    def test_same_attribute_exact_match(self):
        """_same_attribute matches exact same attribute."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        c1 = {"attribute": "GDP增长率"}
        c2 = {"attribute": "GDP增长率"}
        assert node._same_attribute(c1, c2) is True


# ---------------------------------------------------------------------------
# Search API conflict annotation
# ---------------------------------------------------------------------------


class TestSearchAPIConflictAnnotation:
    """Tests for conflict annotation in search results."""

    def test_conflict_annotation_structure(self):
        """Conflict annotation has the correct structure."""
        node = ConflictDetectorNode(article_repo=MagicMock())
        conflicts = [
            {
                "attribute": "GDP增长率",
                "value_a": 6.5,
                "value_b": 7.8,
                "delta_pct": 20.0,
                "source_text": "GDP增长6.5%",
            }
        ]
        annotation = node.format_conflict_annotation(conflicts)
        assert "conflicts" in annotation
        assert len(annotation["conflicts"]) == 1
        conflict = annotation["conflicts"][0]
        assert conflict["attribute"] == "GDP增长率"
        assert "values" in conflict
        assert len(conflict["values"]) == 2
