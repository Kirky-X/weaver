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
        token_budget.truncate = MagicMock(side_effect=lambda text, *args, **kwargs: text[:1000])
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

        from core.evidence.models import EvidenceScoreOutput

        mock_score1 = MagicMock(spec=EvidenceScoreOutput)
        mock_score1.relevance_score = 0.8
        mock_score1.information_density = 0.7
        mock_score1.confidence = 0.75
        mock_score1.key_facts = []

        mock_score2 = MagicMock(spec=EvidenceScoreOutput)
        mock_score2.relevance_score = 0.7
        mock_score2.information_density = 0.6
        mock_score2.confidence = 0.7
        mock_score2.key_facts = []

        async def mock_score(region, title):
            return mock_score1 if "region1" in region else mock_score2

        with patch.object(sampler, "_find_anchor_points", return_value=[100, 200, 300]):
            with patch.object(sampler, "_extract_regions", return_value=["region1", "region2"]):
                with patch.object(sampler, "_score_region", side_effect=mock_score):
                    with patch.object(
                        sampler, "_synthesize_regions", return_value="synthesized text"
                    ):
                        sampled_text, confidence = await sampler.sample_evidence(document)

                        assert sampled_text == "synthesized text"

    @pytest.mark.asyncio
    async def test_low_confidence_falls_back_to_truncation(self, sampler):
        """Test low confidence falls back to truncated document."""
        document = "Long document. " * 1000

        from core.evidence.models import EvidenceScoreOutput

        mock_score = MagicMock(spec=EvidenceScoreOutput)
        mock_score.relevance_score = 0.2
        mock_score.information_density = 0.2
        mock_score.confidence = 0.1
        mock_score.key_facts = []

        async def mock_score_region(region, title):
            return mock_score

        with patch.object(sampler, "_find_anchor_points", return_value=[100, 200]):
            with patch.object(sampler, "_extract_regions", return_value=["region1"]):
                with patch.object(sampler, "_score_region", side_effect=mock_score_region):
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

        anchors = sampler._find_anchor_points(document)

        assert isinstance(anchors, list)
        assert len(anchors) <= sampler._sample_size
        assert all(isinstance(pos, int) for pos in anchors)
        assert all(0 <= pos < len(document) for pos in anchors)

    def test_find_anchors_distributes_positions(self, sampler):
        """Test _find_anchors distributes positions across document."""
        document = "B" * 30000

        anchors = sampler._find_anchor_points(document)

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

        regions = sampler._extract_regions(document, anchors)

        assert isinstance(regions, list)
        assert len(regions) == len(anchors)
        assert all(isinstance(region, str) for region in regions)
        assert all(len(region) > 0 for region in regions)

    def test_sample_regions_respects_region_size(self, sampler):
        """Test _sample_regions respects region_size parameter."""
        document = "Y" * 10000
        anchors = [2000]

        regions = sampler._extract_regions(document, anchors)

        # Region should be approximately region_size
        assert len(regions[0]) <= sampler._region_size + 100  # Some tolerance


class TestMCSamplerScoreRegion:
    """Test MCSampler._score_region method."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance with async LLM."""
        llm_client = AsyncMock()
        token_budget = MagicMock()
        return MCSampler(llm_client, token_budget)

    @pytest.mark.asyncio
    async def test_score_region_calls_llm(self, sampler):
        """Test _score_region calls LLM for scoring a single region."""
        from core.evidence.models import EvidenceScoreOutput

        mock_output = EvidenceScoreOutput(
            relevance_score=0.8,
            information_density=0.7,
            confidence=0.75,
            key_facts=["fact1"],
        )
        sampler._llm.call_at = AsyncMock(return_value=mock_output)

        score = await sampler._score_region("Test region text", title="Test Doc")

        assert isinstance(score, EvidenceScoreOutput)
        assert score.relevance_score == 0.8
        sampler._llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_region_handles_llm_failure(self, sampler):
        """Test _score_region handles LLM failure gracefully."""
        from core.evidence.models import EvidenceScoreOutput

        sampler._llm.call_at = AsyncMock(side_effect=Exception("LLM error"))

        score = await sampler._score_region("Test region text", title="Test Doc")

        # Should return default low score
        assert isinstance(score, EvidenceScoreOutput)
        assert score.relevance_score == 0.3


class TestMCSamplerSynthesizeRegions:
    """Test MCSampler._synthesize_regions method."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance."""
        llm_client = AsyncMock()
        token_budget = MagicMock()
        return MCSampler(llm_client, token_budget)

    def test_synthesize_regions_combines_by_score(self, sampler):
        """Test _synthesize_regions combines scored regions by relevance."""
        from core.evidence.models import EvidenceScoreOutput

        scored_regions = [
            (
                "Important region 1",
                EvidenceScoreOutput(
                    relevance_score=0.9,
                    information_density=0.8,
                    confidence=0.7,
                    key_facts=["fact1"],
                ),
            ),
            (
                "Less important region 2",
                EvidenceScoreOutput(
                    relevance_score=0.7,
                    information_density=0.6,
                    confidence=0.6,
                    key_facts=["fact2"],
                ),
            ),
        ]

        result = sampler._synthesize_regions(scored_regions, title="Test Doc")

        assert isinstance(result, str)
        assert "【文档标题】Test Doc" in result
        assert "fact1" in result

    def test_synthesize_regions_sorts_by_relevance(self, sampler):
        """Test _synthesize_regions sorts regions by relevance * density * confidence."""
        from core.evidence.models import EvidenceScoreOutput

        scored_regions = [
            (
                "Low priority",
                EvidenceScoreOutput(
                    relevance_score=0.3, information_density=0.3, confidence=0.3, key_facts=["low"]
                ),
            ),
            (
                "High priority",
                EvidenceScoreOutput(
                    relevance_score=0.9, information_density=0.9, confidence=0.9, key_facts=["high"]
                ),
            ),
        ]

        result = sampler._synthesize_regions(scored_regions, title="Test")

        assert "high" in result


class TestMCSamplerIntegration:
    """Integration tests for MCSampler."""

    @pytest.mark.asyncio
    async def test_full_sampling_workflow(self):
        """Test complete sampling workflow."""
        from core.evidence.models import EvidenceScoreOutput

        llm_client = AsyncMock()
        token_budget = MagicMock()
        token_budget.truncate = MagicMock(side_effect=lambda text, **kwargs: text[:2000])

        mock_output = EvidenceScoreOutput(
            relevance_score=0.8,
            information_density=0.7,
            confidence=0.75,
            key_facts=["key fact"],
        )
        llm_client.call_at = AsyncMock(return_value=mock_output)

        sampler = MCSampler(llm_client, token_budget, threshold=1000)

        document = "Test document content. " * 100  # ~2500 chars

        # Should trigger MC sampling
        sampled_text, confidence = await sampler.sample_evidence(document)

        assert isinstance(sampled_text, str)
        assert isinstance(confidence, float)
        assert len(sampled_text) > 0
