# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for core.evidence.mc_sampler module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.evidence.mc_sampler import MCSampler


class TestMCSamplerInit:
    """Test MCSampler initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        llm_client = MagicMock()
        token_budget = MagicMock()

        sampler = MCSampler(llm_client, token_budget)

        assert sampler._llm is llm_client
        assert sampler._budget is token_budget
        assert sampler._threshold == 10000
        assert sampler._sample_size == 5
        assert sampler._region_size == 2000
        assert sampler._confidence_threshold == 0.4

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        llm_client = MagicMock()
        token_budget = MagicMock()

        sampler = MCSampler(
            llm_client,
            token_budget,
            threshold=5000,
            sample_size=10,
            region_size=1000,
            confidence_threshold=0.6,
        )

        assert sampler._threshold == 5000
        assert sampler._sample_size == 10
        assert sampler._region_size == 1000
        assert sampler._confidence_threshold == 0.6


class TestMCSamplerSampleEvidence:
    """Test MCSampler.sample_evidence method."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance with mocks."""
        llm_client = AsyncMock()
        token_budget = MagicMock()
        token_budget.truncate = MagicMock(side_effect=lambda text, **kwargs: text[:1000])
        return MCSampler(llm_client, token_budget)

    @pytest.mark.asyncio
    async def test_short_document_returns_truncated(self, sampler):
        """Test short document (< threshold) returns truncated version."""
        document = "Short document text" * 100  # ~2000 chars

        sampled_text, confidence = await sampler.sample_evidence(document)

        # Should truncate but not use MC sampling
        assert len(sampled_text) <= len(document)
        assert confidence >= 0.0

    @pytest.mark.asyncio
    async def test_long_document_triggers_mc_sampling(self, sampler):
        """Test long document (> threshold) triggers MC sampling."""
        document = "Long document. " * 1000  # ~16000 chars

        with patch.object(sampler, "_find_anchors", return_value=[100, 200, 300]):
            with patch.object(sampler, "_sample_regions", return_value=["region1", "region2"]):
                with patch.object(
                    sampler, "_score_regions", return_value=[(0.8, "region1"), (0.7, "region2")]
                ):
                    with patch.object(sampler, "_synthesize", return_value=("synthesized", 0.75)):
                        sampled_text, confidence = await sampler.sample_evidence(document)

                        assert confidence == 0.75

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_truncation(self, sampler):
        """Test low confidence falls back to truncated document."""
        document = "Long document. " * 1000

        with patch.object(sampler, "_find_anchors", return_value=[100, 200]):
            with patch.object(sampler, "_sample_regions", return_value=["region1"]):
                with patch.object(
                    sampler, "_score_regions", return_value=[(0.2, "region1")]
                ):  # Low confidence
                    sampled_text, confidence = await sampler.sample_evidence(document, title="Test")

                    # Should fall back to truncation
                    assert confidence < sampler._confidence_threshold

    @pytest.mark.asyncio
    async def test_empty_document(self, sampler):
        """Test empty document handling."""
        sampled_text, confidence = await sampler.sample_evidence("")

        assert sampled_text == "" or len(sampled_text) == 0


class TestMCSamplerFindAnchors:
    """Test MCSampler._find_anchors method."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance."""
        llm_client = MagicMock()
        token_budget = MagicMock()
        return MCSampler(llm_client, token_budget)

    def test_find_anchors_returns_positions(self, sampler):
        """Test _find_anchors returns list of positions."""
        document = "A" * 20000

        anchors = sampler._find_anchors(document)

        assert isinstance(anchors, list)
        assert len(anchors) <= sampler._sample_size
        assert all(isinstance(pos, int) for pos in anchors)
        assert all(0 <= pos < len(document) for pos in anchors)

    def test_find_anchors_distributes_positions(self, sampler):
        """Test _find_anchors distributes positions across document."""
        document = "B" * 30000

        anchors = sampler._find_anchors(document)

        # Should have multiple anchors
        assert len(anchors) > 1
        # Should be spread across document
        assert min(anchors) < len(document) // 2
        assert max(anchors) > len(document) // 2


class TestMCSamplerSampleRegions:
    """Test MCSampler._sample_regions method."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance."""
        llm_client = MagicMock()
        token_budget = MagicMock()
        return MCSampler(llm_client, token_budget)

    def test_sample_regions_extracts_text(self, sampler):
        """Test _sample_regions extracts text around anchors."""
        document = "X" * 10000
        anchors = [1000, 3000, 5000]

        regions = sampler._sample_regions(document, anchors)

        assert isinstance(regions, list)
        assert len(regions) == len(anchors)
        assert all(isinstance(region, str) for region in regions)
        assert all(len(region) > 0 for region in regions)

    def test_sample_regions_respects_region_size(self, sampler):
        """Test _sample_regions respects region_size parameter."""
        document = "Y" * 10000
        anchors = [2000]

        regions = sampler._sample_regions(document, anchors)

        # Region should be approximately region_size
        assert len(regions[0]) <= sampler._region_size + 100  # Some tolerance


class TestMCSamplerScoreRegions:
    """Test MCSampler._score_regions method."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance with async LLM."""
        llm_client = AsyncMock()
        token_budget = MagicMock()
        return MCSampler(llm_client, token_budget)

    @pytest.mark.asyncio
    async def test_score_regions_calls_llm(self, sampler):
        """Test _score_regions calls LLM for scoring."""
        regions = ["Region 1 text", "Region 2 text"]

        sampler._llm.call = AsyncMock(return_value='{"score": 0.8, "reason": "Good"}')

        scores = await sampler._score_regions(regions, title="Test Doc")

        assert isinstance(scores, list)
        assert len(scores) == len(regions)
        sampler._llm.call.assert_called()

    @pytest.mark.asyncio
    async def test_score_regions_handles_llm_failure(self, sampler):
        """Test _score_regions handles LLM failure gracefully."""
        regions = ["Region 1", "Region 2"]

        sampler._llm.call = AsyncMock(side_effect=Exception("LLM error"))

        scores = await sampler._score_regions(regions)

        # Should return default scores
        assert len(scores) == len(regions)
        assert all(isinstance(score, tuple) for score in scores)


class TestMCSamplerSynthesize:
    """Test MCSampler._synthesize method."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance."""
        llm_client = AsyncMock()
        token_budget = MagicMock()
        return MCSampler(llm_client, token_budget)

    @pytest.mark.asyncio
    async def test_synthesize_combines_regions(self, sampler):
        """Test _synthesize combines scored regions."""
        scored_regions = [
            (0.9, "Important region 1"),
            (0.7, "Less important region 2"),
        ]

        sampler._llm.call = AsyncMock(
            return_value='{"synthesis": "Combined text", "confidence": 0.85}'
        )

        synthesized, confidence = await sampler._synthesize(scored_regions)

        assert isinstance(synthesized, str)
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    @pytest.mark.asyncio
    async def test_synthesize_handles_failure(self, sampler):
        """Test _synthesize handles LLM failure."""
        scored_regions = [(0.8, "Region text")]

        sampler._llm.call = AsyncMock(side_effect=Exception("Synthesis failed"))

        synthesized, confidence = await sampler._synthesize(scored_regions)

        # Should return fallback (first region)
        assert isinstance(synthesized, str)
        assert len(synthesized) > 0


class TestMCSamplerIntegration:
    """Integration tests for MCSampler."""

    @pytest.mark.asyncio
    async def test_full_sampling_workflow(self):
        """Test complete sampling workflow."""
        llm_client = AsyncMock()
        token_budget = MagicMock()
        token_budget.truncate = MagicMock(side_effect=lambda text, **kwargs: text[:2000])

        sampler = MCSampler(llm_client, token_budget, threshold=1000)

        document = "Test document content. " * 100  # ~2500 chars

        # Should trigger MC sampling
        sampled_text, confidence = await sampler.sample_evidence(document)

        assert isinstance(sampled_text, str)
        assert isinstance(confidence, float)
        assert len(sampled_text) > 0
