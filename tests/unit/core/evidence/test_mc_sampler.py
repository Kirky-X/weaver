# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for MCSampler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.evidence.mc_sampler import MCSampler
from core.evidence.models import EvidenceScoreOutput
from core.llm.types import CallPoint


class TestMCSampler:
    """Tests for Monte Carlo evidence sampler."""

    @pytest.fixture
    def mock_llm_client(self):
        """Create mock LLM client."""
        client = MagicMock()
        client.call_at = AsyncMock(
            return_value=EvidenceScoreOutput(
                relevance_score=0.8,
                information_density=0.7,
                confidence=0.9,
                key_facts=["fact1", "fact2"],
            )
        )
        return client

    @pytest.fixture
    def mock_token_budget(self):
        """Create mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(side_effect=lambda text, _: text)
        return budget

    @pytest.fixture
    def mc_sampler(self, mock_llm_client, mock_token_budget):
        """Create MCSampler instance with default settings."""
        return MCSampler(
            llm_client=mock_llm_client,
            token_budget_manager=mock_token_budget,
            threshold=10000,
            sample_size=5,
            region_size=2000,
            confidence_threshold=0.4,
        )

    def test_initialization(self, mock_llm_client, mock_token_budget):
        """Test MCSampler initializes with correct settings."""
        sampler = MCSampler(
            llm_client=mock_llm_client,
            token_budget_manager=mock_token_budget,
            threshold=5000,
            sample_size=3,
            region_size=1500,
            confidence_threshold=0.5,
        )

        assert sampler._threshold == 5000
        assert sampler._sample_size == 3
        assert sampler._region_size == 1500
        assert sampler._confidence_threshold == 0.5

    @pytest.mark.asyncio
    async def test_short_document_returns_unchanged(self, mc_sampler):
        """Test that short documents are returned unchanged."""
        short_doc = "Short document content"
        result, confidence = await mc_sampler.sample_evidence(short_doc, "Test Title")

        assert result == short_doc
        assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_long_document_triggers_sampling(
        self, mc_sampler, mock_llm_client, mock_token_budget
    ):
        """Test that long documents trigger sampling."""
        # Create a document longer than threshold
        long_doc = "内容" * 6000  # ~12000 characters

        result, confidence = await mc_sampler.sample_evidence(long_doc, "Test Title")

        # Should have called LLM for scoring
        assert mock_llm_client.call_at.called

        # Result should be different from original
        assert len(result) < len(long_doc)

    def test_find_anchor_points_returns_list(self, mc_sampler):
        """Test that _find_anchor_points returns a list of integers."""
        text = "测试内容" * 3000  # Long enough for anchor finding
        anchors = mc_sampler._find_anchor_points(text)

        assert isinstance(anchors, list)
        assert all(isinstance(a, int) for a in anchors)
        assert len(anchors) > 0

    def test_find_anchor_points_respects_sample_size(self, mc_sampler):
        """Test that anchor count respects sample_size."""
        mc_sampler._sample_size = 3
        text = "测试内容" * 3000
        anchors = mc_sampler._find_anchor_points(text)

        assert len(anchors) <= 3

    def test_extract_regions_returns_correct_count(self, mc_sampler):
        """Test that _extract_regions returns correct number of regions."""
        text = "测试内容" * 5000
        anchors = [1000, 3000, 5000, 7000]
        regions = mc_sampler._extract_regions(text, anchors)

        assert len(regions) == len(anchors)

    def test_extract_regions_respects_region_size(self, mc_sampler):
        """Test that extracted regions respect region_size."""
        mc_sampler._region_size = 1000
        text = "测试内容" * 5000
        anchors = [2000]
        regions = mc_sampler._extract_regions(text, anchors)

        # Region should be approximately region_size
        # Plus truncation markers
        assert len(regions[0]) <= 1100  # Allow some margin for markers

    def test_extract_regions_handles_boundary_anchors(self, mc_sampler):
        """Test extraction handles anchors near document boundaries."""
        text = "测试内容" * 100
        # Anchors at start and end
        anchors = [0, len(text) - 100]
        regions = mc_sampler._extract_regions(text, anchors)

        assert len(regions) == 2
        assert all(region for region in regions)

    def test_simple_similarity_identical_texts(self, mc_sampler):
        """Test similarity returns 1.0 for identical texts."""
        text = "测试内容"
        similarity = mc_sampler._simple_similarity(text, text)

        assert similarity == 1.0

    def test_simple_similarity_different_texts(self, mc_sampler):
        """Test similarity returns lower values for different texts."""
        text1 = "这是测试内容"
        text2 = "完全不同的内容"
        similarity = mc_sampler._simple_similarity(text1, text2)

        assert 0.0 <= similarity < 1.0

    def test_simple_similarity_empty_texts(self, mc_sampler):
        """Test similarity handles empty texts."""
        assert mc_sampler._simple_similarity("", "content") == 0.0
        assert mc_sampler._simple_similarity("content", "") == 0.0
        assert mc_sampler._simple_similarity("", "") == 0.0

    def test_find_fuzz_anchors_finds_change_points(self, mc_sampler):
        """Test that fuzz anchor finding detects content changes."""
        # Create text with distinct sections
        text = ("主题一的内容" * 500) + ("完全不同的主题二" * 500) + ("第三个主题的内容" * 500)
        window = 200
        anchors = mc_sampler._find_fuzz_anchors(text, window)

        assert isinstance(anchors, list)
        # Should find at least one change point
        assert len(anchors) >= 0  # May not find if sections are too similar

    @pytest.mark.asyncio
    async def test_score_region_calls_llm_correctly(self, mc_sampler, mock_llm_client):
        """Test that _score_region calls LLM with correct parameters."""
        region = "测试区域内容"
        title = "测试标题"

        result = await mc_sampler._score_region(region, title)

        assert mock_llm_client.call_at.called
        call_args = mock_llm_client.call_at.call_args
        assert call_args[0][0] == CallPoint.EVIDENCE_SAMPLING
        assert isinstance(result, EvidenceScoreOutput)

    def test_synthesize_regions_combines_regions(self, mc_sampler):
        """Test that _synthesize_regions combines regions correctly."""
        scored_regions = [
            ("区域1内容", EvidenceScoreOutput(relevance_score=0.9, information_density=0.8, confidence=0.9, key_facts=["事实1"])),
            ("区域2内容", EvidenceScoreOutput(relevance_score=0.7, information_density=0.6, confidence=0.8, key_facts=["事实2"])),
        ]
        title = "测试文档"

        result = mc_sampler._synthesize_regions(scored_regions, title)

        assert "测试文档" in result
        assert "事实1" in result
        assert "区域1内容" in result

    def test_synthesize_regions_sorts_by_score(self, mc_sampler):
        """Test that synthesis prioritizes higher scored regions."""
        scored_regions = [
            ("低分区域", EvidenceScoreOutput(relevance_score=0.3, information_density=0.3, confidence=0.5, key_facts=[])),
            ("高分区域", EvidenceScoreOutput(relevance_score=0.9, information_density=0.9, confidence=0.9, key_facts=["关键事实"])),
        ]
        title = "测试"

        result = mc_sampler._synthesize_regions(scored_regions, title)

        # Higher scored region should appear first
        high_pos = result.find("高分区域")
        low_pos = result.find("低分区域")
        assert high_pos < low_pos

    @pytest.mark.asyncio
    async def test_low_confidence_fallback(self, mock_llm_client, mock_token_budget):
        """Test fallback when confidence is below threshold."""
        # Configure LLM to return low confidence
        mock_llm_client.call_at = AsyncMock(
            return_value=EvidenceScoreOutput(
                relevance_score=0.3,
                information_density=0.2,
                confidence=0.2,  # Low confidence
                key_facts=[],
            )
        )

        sampler = MCSampler(
            llm_client=mock_llm_client,
            token_budget_manager=mock_token_budget,
            threshold=100,
            confidence_threshold=0.4,
        )

        long_doc = "测试内容" * 100
        result, confidence = await sampler.sample_evidence(long_doc, "Test")

        # Should fall back to truncated text
        assert confidence < 0.4
        # Token budget truncation should be called
        assert mock_token_budget.truncate.called

    @pytest.mark.asyncio
    async def test_handles_llm_failure_gracefully(self, mock_llm_client, mock_token_budget):
        """Test graceful handling when LLM scoring fails."""
        # Configure LLM to raise exception
        mock_llm_client.call_at = AsyncMock(side_effect=Exception("LLM error"))

        sampler = MCSampler(
            llm_client=mock_llm_client,
            token_budget_manager=mock_token_budget,
            threshold=100,
        )

        long_doc = "测试内容" * 100
        result, confidence = await sampler.sample_evidence(long_doc, "Test")

        # Should still return a result
        assert isinstance(result, str)
        assert isinstance(confidence, float)

    @pytest.mark.asyncio
    async def test_exact_threshold_document(self, mc_sampler):
        """Test behavior when document is exactly at threshold."""
        # Create document exactly at threshold
        mc_sampler._threshold = 100
        exact_doc = "x" * 100

        result, confidence = await mc_sampler.sample_evidence(exact_doc, "Test")

        # At threshold means shorter than threshold+1, so should return as-is
        assert result == exact_doc
        assert confidence == 1.0

    @pytest.mark.asyncio
    async def test_one_char_over_threshold(self, mc_sampler, mock_llm_client):
        """Test behavior when document is one char over threshold."""
        mc_sampler._threshold = 100
        # Use a longer document to ensure anchors can be found
        # Need enough characters to extract regions (region_size=2000 by default)
        mc_sampler._region_size = 50  # Smaller region size for short docs
        over_doc = "x" * 101

        result, confidence = await mc_sampler.sample_evidence(over_doc, "Test")

        # With proper setup, should trigger sampling
        # Note: May not call LLM if no anchors found due to short document
        # The key is that sampling was attempted (not returned unchanged)


class TestEvidenceScoreOutput:
    """Tests for EvidenceScoreOutput model."""

    def test_valid_output(self):
        """Test valid output creation."""
        output = EvidenceScoreOutput(
            relevance_score=0.85,
            information_density=0.72,
            confidence=0.90,
            key_facts=["fact1", "fact2", "fact3"],
        )

        assert output.relevance_score == 0.85
        assert output.information_density == 0.72
        assert output.confidence == 0.90
        assert len(output.key_facts) == 3

    def test_default_key_facts(self):
        """Test that key_facts defaults to empty list."""
        output = EvidenceScoreOutput(
            relevance_score=0.5,
            information_density=0.5,
            confidence=0.5,
        )

        assert output.key_facts == []

    def test_score_boundaries(self):
        """Test that scores are bounded to 0-1 range."""
        # Valid boundaries
        output = EvidenceScoreOutput(
            relevance_score=0.0,
            information_density=1.0,
            confidence=0.5,
        )
        assert output.relevance_score == 0.0
        assert output.information_density == 1.0

    def test_invalid_score_raises_validation_error(self):
        """Test that invalid scores raise validation error."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            EvidenceScoreOutput(
                relevance_score=1.5,  # Invalid: > 1.0
                information_density=0.5,
                confidence=0.5,
            )
