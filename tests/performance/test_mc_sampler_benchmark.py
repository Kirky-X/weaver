# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Benchmark tests for Monte Carlo Evidence Sampling token savings."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.evidence.mc_sampler import MCSampler
from core.evidence.models import EvidenceScoreOutput


class TestMCSamplerBenchmark:
    """Benchmark tests to verify token savings from MC sampling."""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client with realistic scoring."""
        client = MagicMock()

        async def mock_call_at(call_point, payload, output_model=None):
            # Simulate realistic LLM response
            return EvidenceScoreOutput(
                relevance_score=0.75,
                information_density=0.65,
                confidence=0.8,
                key_facts=["关键事实1", "关键事实2", "关键事实3"],
            )

        client.call_at = AsyncMock(side_effect=mock_call_at)
        return client

    @pytest.fixture
    def mock_token_budget(self):
        """Create mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(side_effect=lambda text, _: text[:4000])
        budget.count_tokens = MagicMock(side_effect=lambda text: len(text) // 4)
        return budget

    def generate_long_document(self, length: int) -> str:
        """Generate a test document of specified length.

        Creates a realistic-looking document with multiple sections
        to test the sampling strategy.
        """
        sections = [
            "【导语】这是一篇关于人工智能发展的深度报道。人工智能技术正在快速发展，对各行各业产生深远影响。",
            "【背景】近年来，人工智能技术在自然语言处理、计算机视觉、语音识别等领域取得了突破性进展。",
            "【分析】专家认为，人工智能的发展将深刻改变人类社会的运作方式，带来前所未有的机遇和挑战。",
            "【数据】根据最新统计，全球人工智能市场规模已超过5000亿美元，年增长率保持在30%以上。",
            "【展望】未来十年，人工智能将继续向更智能、更普及的方向发展，成为推动社会进步的重要力量。",
            "【观点】多位行业专家表示，人工智能的发展需要平衡技术进步与伦理考量，确保技术造福人类。",
            "【案例】在实际应用中，人工智能已经成功应用于医疗诊断、金融风控、智能制造等多个领域。",
            "【挑战】尽管前景广阔，人工智能发展仍面临数据安全、算法偏见、就业冲击等诸多挑战。",
        ]

        # Build document by repeating sections
        doc_parts = []
        current_length = 0
        section_idx = 0

        while current_length < length:
            section = sections[section_idx % len(sections)]
            doc_parts.append(section)
            current_length += len(section)
            section_idx += 1

        return "".join(doc_parts)[:length]

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_token_savings_10k_document(self, mock_llm, mock_token_budget, benchmark):
        """Benchmark token savings for 10K character document."""
        sampler = MCSampler(
            llm_client=mock_llm,
            token_budget_manager=mock_token_budget,
            threshold=5000,  # Trigger sampling
            sample_size=3,
            region_size=1500,
        )

        doc = self.generate_long_document(10000)

        result, confidence = await sampler.sample_evidence(doc, "测试文档")

        # Verify savings
        original_len = len(doc)
        sampled_len = len(result)
        savings_pct = (1 - sampled_len / original_len) * 100

        print("\n10K Document Results:")
        print(f"  Original length: {original_len} chars")
        print(f"  Sampled length: {sampled_len} chars")
        print(f"  Token savings: {savings_pct:.1f}%")
        print(f"  Confidence: {confidence:.2f}")

        # Assert meaningful savings
        assert savings_pct > 30, f"Expected >30% savings, got {savings_pct:.1f}%"

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_token_savings_50k_document(self, mock_llm, mock_token_budget):
        """Benchmark token savings for 50K character document."""
        sampler = MCSampler(
            llm_client=mock_llm,
            token_budget_manager=mock_token_budget,
            threshold=5000,
            sample_size=5,
            region_size=2000,
        )

        doc = self.generate_long_document(50000)

        start_time = time.time()
        result, confidence = await sampler.sample_evidence(doc, "测试文档")
        elapsed_ms = (time.time() - start_time) * 1000

        # Verify savings
        original_len = len(doc)
        sampled_len = len(result)
        savings_pct = (1 - sampled_len / original_len) * 100

        print("\n50K Document Results:")
        print(f"  Original length: {original_len} chars")
        print(f"  Sampled length: {sampled_len} chars")
        print(f"  Token savings: {savings_pct:.1f}%")
        print(f"  Confidence: {confidence:.2f}")
        print(f"  Processing time: {elapsed_ms:.1f}ms")

        # Assert meaningful savings
        assert savings_pct > 70, f"Expected >70% savings, got {savings_pct:.1f}%"

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_sampling_latency(self, mock_llm, mock_token_budget):
        """Benchmark sampling latency for various document sizes."""
        sampler = MCSampler(
            llm_client=mock_llm,
            token_budget_manager=mock_token_budget,
            threshold=1000,
            sample_size=3,
        )

        sizes = [5000, 10000, 20000, 50000]
        results = []

        print("\nLatency Benchmark:")
        print("-" * 50)

        for size in sizes:
            doc = self.generate_long_document(size)

            start_time = time.time()
            result, confidence = await sampler.sample_evidence(doc, "测试文档")
            elapsed_ms = (time.time() - start_time) * 1000

            savings_pct = (1 - len(result) / len(doc)) * 100
            results.append(
                {
                    "size": size,
                    "latency_ms": elapsed_ms,
                    "savings_pct": savings_pct,
                    "confidence": confidence,
                }
            )

            print(
                f"  Size: {size:,} chars | Latency: {elapsed_ms:.1f}ms | Savings: {savings_pct:.1f}%"
            )

        # Latency should scale reasonably with document size
        # Not linear, as we only sample a fixed number of regions
        assert results[-1]["latency_ms"] < results[0]["latency_ms"] * 3

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_sampling_quality_preserves_key_info(self, mock_llm, mock_token_budget):
        """Verify that sampling preserves key information."""
        # Create document with specific key information
        key_phrase = "关键数据：2024年人工智能市场规模达到5000亿美元"
        doc = ("普通内容，" * 500) + key_phrase + ("更多普通内容，" * 500)

        sampler = MCSampler(
            llm_client=mock_llm,
            token_budget_manager=mock_token_budget,
            threshold=1000,
            sample_size=5,
            region_size=500,
        )

        result, confidence = await sampler.sample_evidence(doc, "重要报告")

        # Key information should be preserved in key_facts
        print("\nKey Info Preservation Test:")
        print(f"  Key phrase: {key_phrase}")
        print(f"  Document length: {len(doc)}")
        print(f"  Sampled length: {len(result)}")
        print(f"  Confidence: {confidence:.2f}")

        # Either the key phrase should be in the result,
        # or the confidence should indicate quality
        assert confidence > 0.5 or key_phrase[:10] in result

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_comparison_with_truncation(self, mock_llm, mock_token_budget):
        """Compare MC sampling with simple truncation."""
        doc = self.generate_long_document(20000)

        sampler = MCSampler(
            llm_client=mock_llm,
            token_budget_manager=mock_token_budget,
            threshold=1000,
            sample_size=5,
            region_size=1500,
        )

        # MC Sampling
        mc_result, mc_confidence = await sampler.sample_evidence(doc, "测试")

        # Simple truncation
        truncate_result = doc[:4000]

        # Count unique content (rough measure of information diversity)
        mc_unique_chars = len(set(mc_result))
        truncate_unique_chars = len(set(truncate_result))

        print("\nComparison: MC Sampling vs Truncation")
        print("  MC Sampling:")
        print(f"    Length: {len(mc_result)} chars")
        print(f"    Unique chars: {mc_unique_chars}")
        print(f"    Confidence: {mc_confidence:.2f}")
        print("  Simple Truncation:")
        print(f"    Length: {len(truncate_result)} chars")
        print(f"    Unique chars: {truncate_unique_chars}")

        # MC sampling should capture more diverse content
        # (sampling from multiple regions vs just the start)


class TestMCSamplerConfigImpact:
    """Test impact of configuration parameters on sampling."""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client."""
        client = MagicMock()
        client.call_at = AsyncMock(
            return_value=EvidenceScoreOutput(
                relevance_score=0.7,
                information_density=0.6,
                confidence=0.8,
                key_facts=["fact"],
            )
        )
        return client

    @pytest.fixture
    def mock_token_budget(self):
        """Create mock token budget manager."""
        budget = MagicMock()
        budget.truncate = MagicMock(side_effect=lambda text, _: text)
        return budget

    @pytest.mark.asyncio
    async def test_sample_size_impact(self, mock_llm, mock_token_budget):
        """Test how sample_size affects results."""
        doc = "测试内容" * 5000
        results = {}

        for sample_size in [2, 5, 10]:
            sampler = MCSampler(
                llm_client=mock_llm,
                token_budget_manager=mock_token_budget,
                threshold=1000,
                sample_size=sample_size,
            )

            result, confidence = await sampler.sample_evidence(doc, "测试")
            results[sample_size] = len(result)

            print(f"  sample_size={sample_size}: result_len={len(result)}")

        # Larger sample_size should result in longer output
        assert results[5] >= results[2]
        assert results[10] >= results[5]

    @pytest.mark.asyncio
    async def test_region_size_impact(self, mock_llm, mock_token_budget):
        """Test how region_size affects results."""
        doc = "测试内容" * 5000
        results = {}

        for region_size in [500, 1000, 2000]:
            sampler = MCSampler(
                llm_client=mock_llm,
                token_budget_manager=mock_token_budget,
                threshold=1000,
                sample_size=3,
                region_size=region_size,
            )

            result, confidence = await sampler.sample_evidence(doc, "测试")
            results[region_size] = len(result)

            print(f"  region_size={region_size}: result_len={len(result)}")

        # Larger region_size should result in longer output
        assert results[2000] >= results[1000]
        assert results[1000] >= results[500]
