# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""REVISED (llm-token-optimization T005): 区域评分已批量化.

原 P1-2 测试断言 asyncio.gather 并发评分（每区域一次调用）；
批量化后 5 个区域合并为 1 次 LLM 调用，时延断言的前提不复存在，
改断言新的调用次数契约：5 区域全程恰好 1 次 call_at。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.evidence.models import EvidenceBatchScoreOutput, EvidenceScoreOutput


@pytest.fixture
def sampler_with_mocks():
    """Create MCSampler with mocked deps + 5 fixed regions."""
    from core.evidence.mc_sampler import MCSampler

    llm = AsyncMock()
    budget = MagicMock()
    budget.truncate = MagicMock(side_effect=lambda text, *a, **k: text)
    sampler = MCSampler(
        llm_client=llm,
        token_budget_manager=budget,
        threshold=1,  # Force MC sampling path
        sample_size=5,
        region_size=100,
        confidence_threshold=0.0,  # Always use sampled text
    )

    regions = [f"region_{i} " + "x" * 95 for i in range(5)]
    sampler._find_anchor_points = MagicMock(return_value=[0, 1, 2, 3, 4])
    sampler._extract_regions = MagicMock(return_value=regions)
    sampler._synthesize_regions = MagicMock(return_value="synthesized")

    return sampler, regions


class TestMCSamplerBatchedScoring:
    """5 区域全程恰好 1 次 LLM 调用（批量化契约）."""

    @pytest.mark.asyncio
    async def test_sample_evidence_scores_all_regions_in_one_llm_call(
        self, sampler_with_mocks
    ) -> None:
        sampler, regions = sampler_with_mocks

        sampler._llm.call_at = AsyncMock(
            return_value=EvidenceBatchScoreOutput(
                scores=[
                    EvidenceScoreOutput(
                        relevance_score=0.8,
                        information_density=0.8,
                        confidence=0.9,
                        key_facts=[],
                    )
                    for _ in regions
                ]
            )
        )

        sampled_text, confidence = await sampler.sample_evidence("document" * 200, title="test")

        assert sampler._llm.call_at.await_count == 1
        payload = sampler._llm.call_at.await_args.args[1]
        assert len(payload["regions"]) == len(regions)
        assert sampled_text == "synthesized"
        assert confidence > 0
