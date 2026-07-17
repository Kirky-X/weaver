# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""RED test for MCSampler concurrent region scoring — P1-2 fix.

``sample_evidence`` currently scores regions in a sequential for-loop,
making total time = N × single_region_time. With LLM scoring latency
(~300ms each), 5 regions take 1.5s serial vs ~0.3s concurrent.

This test asserts ``asyncio.gather`` concurrency: total time ≤ 2×
single-region time (allowing scheduling overhead).

See ``temp/report.md`` P1-2 (MC 采样器并发) and specmark change
``fix-pipeline-deadcode-perf`` T020-T021.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.evidence.models import EvidenceScoreOutput


@pytest.fixture
def sampler_with_mocks():
    """Create MCSampler with mocked deps + 5 fixed regions."""
    from core.evidence.mc_sampler import MCSampler

    llm = AsyncMock()
    budget = MagicMock()
    sampler = MCSampler(
        llm_client=llm,
        token_budget_manager=budget,
        threshold=1,  # Force MC sampling path
        sample_size=5,
        region_size=100,
        confidence_threshold=0.0,  # Always use sampled text
    )

    # 5 fixed regions
    regions = [f"region_{i} " + "x" * 95 for i in range(5)]
    sampler._find_anchor_points = MagicMock(return_value=[0, 1, 2, 3, 4])
    sampler._extract_regions = MagicMock(return_value=regions)
    sampler._synthesize_regions = MagicMock(return_value="synthesized")

    return sampler, regions


class TestMCSamplerConcurrentScoring:
    """Tests that sample_evidence scores regions concurrently."""

    @pytest.mark.asyncio
    async def test_sample_evidence_regions_scored_concurrently(self, sampler_with_mocks) -> None:
        """5 regions scored in parallel: total ≤ 2× single-region time."""
        sampler, regions = sampler_with_mocks

        single_region_delay = 0.3

        async def _slow_score(region: str, title: str) -> EvidenceScoreOutput:
            await asyncio.sleep(single_region_delay)
            return EvidenceScoreOutput(
                relevance_score=0.8,
                information_density=0.8,
                confidence=0.9,
                key_facts=[],
            )

        sampler._score_region = _slow_score

        start = time.monotonic()
        await sampler.sample_evidence("document" * 200, title="test")
        elapsed = time.monotonic() - start

        # Serial 5 × 0.3s = 1.5s; concurrent ≈ 0.3s.
        # Allow 2× single-region = 0.6s ceiling for scheduling overhead.
        ceiling = single_region_delay * 2
        assert elapsed < ceiling, (
            f"Expected concurrent scoring < {ceiling:.2f}s; "
            f"got {elapsed:.2f}s (serial would be ~{single_region_delay * len(regions):.2f}s)"
        )
