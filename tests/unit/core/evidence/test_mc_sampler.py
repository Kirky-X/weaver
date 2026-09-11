# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

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

        async def mock_batch(regions, title):
            return [(r, mock_score1 if "region1" in r else mock_score2) for r in regions]

        with patch.object(sampler, "_find_anchor_points", return_value=[100, 200, 300]):
            with patch.object(sampler, "_extract_regions", return_value=["region1", "region2"]):
                with patch.object(sampler, "_score_regions_batch", side_effect=mock_batch):
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

        async def mock_batch(regions, title):
            return [(r, mock_score) for r in regions]

        with patch.object(sampler, "_find_anchor_points", return_value=[100, 200]):
            with patch.object(sampler, "_extract_regions", return_value=["region1"]):
                with patch.object(sampler, "_score_regions_batch", side_effect=mock_batch):
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


class TestMCSamplerBatchCallContract:
    """批量评分的 call_at 契约：EVIDENCE_SAMPLING 调用点 + 批量输出模型."""

    @pytest.fixture
    def sampler(self):
        """Create MCSampler instance with async LLM."""
        llm_client = AsyncMock()
        token_budget = MagicMock()
        token_budget.truncate = MagicMock(side_effect=lambda text, *a, **k: text)
        return MCSampler(llm_client, token_budget)

    @pytest.mark.asyncio
    async def test_batch_call_uses_evidence_sampling_call_point_and_model(self, sampler):
        """call_at 以 EVIDENCE_SAMPLING 调用点 + EvidenceBatchScoreOutput 模型发起."""
        from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput
        from core.llm.types import CallPoint

        sampler._llm.call_at = AsyncMock(
            return_value=EvidenceBatchScoreOutput(
                scores=[
                    EvidenceScoreOutput(
                        relevance_score=0.8,
                        information_density=0.7,
                        confidence=0.75,
                        key_facts=["fact1"],
                    )
                ]
            )
        )

        result = await sampler._score_regions_batch(["Test region text"], title="Test Doc")

        sampler._llm.call_at.assert_awaited_once()
        call_point_arg = sampler._llm.call_at.await_args.args[0]
        output_model_kw = sampler._llm.call_at.await_args.kwargs["output_model"]
        assert call_point_arg == CallPoint.EVIDENCE_SAMPLING
        assert output_model_kw is EvidenceBatchScoreOutput
        assert result[0][1].relevance_score == 0.8

    @pytest.mark.asyncio
    async def test_batch_regions_truncated_via_budget(self, sampler):
        """每个区域经 TokenBudgetManager.truncate 后进入 payload."""
        from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput

        sampler._llm.call_at = AsyncMock(
            return_value=EvidenceBatchScoreOutput(
                scores=[
                    EvidenceScoreOutput(
                        relevance_score=0.5, information_density=0.5, confidence=0.5
                    )
                ]
            )
        )

        await sampler._score_regions_batch(["raw region text"], title="T")

        sampler._budget.truncate.assert_called_once()


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
        token_budget.truncate = MagicMock(side_effect=lambda text, *a, **k: text[:2000])

        from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput

        async def fake_call_at(call_point, payload, **kwargs):
            n = len(payload["regions"])
            return EvidenceBatchScoreOutput(
                scores=[
                    EvidenceScoreOutput(
                        relevance_score=0.8,
                        information_density=0.7,
                        confidence=0.75,
                        key_facts=["key fact"],
                    )
                    for _ in range(n)
                ]
            )

        llm_client.call_at = AsyncMock(side_effect=fake_call_at)

        sampler = MCSampler(llm_client, token_budget, threshold=1000)

        document = "Test document content. " * 100  # ~2500 chars

        # Should trigger MC sampling
        sampled_text, confidence = await sampler.sample_evidence(document)

        assert isinstance(sampled_text, str)
        assert isinstance(confidence, float)
        assert len(sampled_text) > 0


class TestMCSamplerBatchScoring:
    """区域评分批量化：N 次 LLM 调用合并为 1 次（R-evidence-001）."""

    @pytest.fixture
    def sampler(self):
        llm_client = AsyncMock()
        token_budget = MagicMock()
        token_budget.truncate = MagicMock(side_effect=lambda text, *a, **k: text)
        return MCSampler(llm_client, token_budget)

    @staticmethod
    def _batch_output(score_triples):
        from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput

        return EvidenceBatchScoreOutput(
            scores=[
                EvidenceScoreOutput(
                    relevance_score=r, information_density=d, confidence=c, key_facts=[]
                )
                for (r, d, c) in score_triples
            ]
        )

    @pytest.mark.asyncio
    async def test_five_regions_scored_in_single_llm_call(self, sampler):
        """5 区域采样全程只发起 1 次 LLM 调用，payload 携带编号区域."""
        document = "Long document. " * 1000

        with patch.object(sampler, "_find_anchor_points", return_value=[100, 200, 300, 400, 500]):
            with patch.object(
                sampler, "_extract_regions", return_value=["r1", "r2", "r3", "r4", "r5"]
            ):
                with patch.object(sampler, "_synthesize_regions", return_value="synth"):
                    sampler._llm.call_at.return_value = self._batch_output([(0.8, 0.7, 0.7)] * 5)
                    await sampler.sample_evidence(document, title="T")

        assert sampler._llm.call_at.await_count == 1
        payload = sampler._llm.call_at.await_args.args[1]
        assert set(payload["regions"].keys()) == {"R1", "R2", "R3", "R4", "R5"}
        assert payload["regions"]["R1"] == "r1"

    @pytest.mark.asyncio
    async def test_scores_align_by_region_index(self, sampler):
        """批量返回的评分按索引对齐回各区域."""
        sampler._llm.call_at.return_value = self._batch_output([(0.9, 0.8, 0.7), (0.1, 0.2, 0.3)])

        result = await sampler._score_regions_batch(["regionA", "regionB"], "T")

        assert sampler._llm.call_at.await_count == 1
        assert result[0] == ("regionA", result[0][1])
        assert result[0][1].relevance_score == 0.9
        assert result[1][0] == "regionB"
        assert result[1][1].relevance_score == 0.1

    @pytest.mark.asyncio
    async def test_length_mismatch_retries_then_degrades(self, sampler):
        """数组长度与区域数不符：重试 1 次后仍不符 → 全部区域取默认低分."""
        sampler._llm.call_at.return_value = self._batch_output([(0.9, 0.9, 0.9)])

        result = await sampler._score_regions_batch(["r1", "r2"], "T")

        assert sampler._llm.call_at.await_count == 2
        for _, score in result:
            assert score.relevance_score == 0.3
            assert score.information_density == 0.3
            assert score.confidence == 0.0

    @pytest.mark.asyncio
    async def test_length_mismatch_second_attempt_aligned(self, sampler):
        """首次长度不符、重试成功 → 采用重试结果正常对齐."""
        sampler._llm.call_at.side_effect = [
            self._batch_output([(0.9, 0.9, 0.9)]),
            self._batch_output([(0.8, 0.8, 0.8), (0.6, 0.6, 0.6)]),
        ]

        result = await sampler._score_regions_batch(["r1", "r2"], "T")

        assert sampler._llm.call_at.await_count == 2
        assert result[0][1].relevance_score == 0.8
        assert result[1][1].relevance_score == 0.6

    @pytest.mark.asyncio
    async def test_region_id_echo_aligns_out_of_order_scores(self, sampler):
        """模型回显 region_id 但乱序 → 按 region_id 映射而非数组顺序."""
        from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput

        scores = [
            EvidenceScoreOutput(
                region_id="R2", relevance_score=0.2, information_density=0.2, confidence=0.2
            ),
            EvidenceScoreOutput(
                region_id="R1", relevance_score=0.8, information_density=0.8, confidence=0.8
            ),
        ]
        sampler._llm.call_at.return_value = EvidenceBatchScoreOutput(scores=scores)

        result = await sampler._score_regions_batch(["regionA", "regionB"], "T")

        assert result[0] == ("regionA", scores[1])
        assert result[1] == ("regionB", scores[0])

    @pytest.mark.asyncio
    async def test_incomplete_region_id_echo_falls_back_to_order(self, sampler):
        """region_id 回显不完整 → 回退数组顺序对齐."""
        from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput

        scores = [
            EvidenceScoreOutput(
                region_id="R1", relevance_score=0.7, information_density=0.7, confidence=0.7
            ),
            EvidenceScoreOutput(
                region_id="", relevance_score=0.4, information_density=0.4, confidence=0.4
            ),
        ]
        sampler._llm.call_at.return_value = EvidenceBatchScoreOutput(scores=scores)

        result = await sampler._score_regions_batch(["regionA", "regionB"], "T")

        assert result[0][1].relevance_score == 0.7
        assert result[1][1].relevance_score == 0.4

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_all_regions(self, sampler):
        """LLM 调用异常 → 全部区域默认低分，不向上传播."""
        sampler._llm.call_at.side_effect = RuntimeError("api down")

        result = await sampler._score_regions_batch(["r1", "r2"], "T")

        assert sampler._llm.call_at.await_count == 2
        for _, score in result:
            assert score.relevance_score == 0.3
            assert score.confidence == 0.0
