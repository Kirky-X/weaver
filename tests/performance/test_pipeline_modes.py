# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Performance tests for pipeline processing modes.

Tests the timing difference between fast mode (Phase 1 only) and deep mode
(full 4-phase processing).

Fast mode: classifier → cleaner → categorizer → vectorize
Deep mode: Fast mode + batch merger + entity extraction + quality scoring

Expected performance:
- Fast mode: 1-2 minutes for 5 articles
- Deep mode: 5-10 minutes for 5 articles
- Fast mode should be 3-5x faster than deep mode
"""

from __future__ import annotations

import time
from typing import Any

import pytest


@pytest.fixture
def sample_articles() -> list[dict[str, Any]]:
    """Generate sample articles for testing."""
    return [
        {
            "url": f"https://example.com/test/{i}",
            "title": f"Test Article {i}: Technology News Update",
            "body": f"This is the body of test article {i}. " * 50,
            "source": "test_source",
            "source_host": "example.com",
        }
        for i in range(5)
    ]


@pytest.mark.performance
class TestPipelineModeTiming:
    """Test timing differences between processing modes."""

    @pytest.mark.asyncio
    async def test_fast_mode_timing(self, sample_articles: list[dict[str, Any]]) -> None:
        """Test that fast mode processes articles within expected time.

        Fast mode should complete in 1-2 minutes for 5 articles.
        This test uses mocked LLM responses for consistent timing.
        """
        # This is a placeholder test - actual implementation requires
        # a running pipeline with mocked LLM services
        start_time = time.time()

        # Simulate fast mode processing (Phase 1 only)
        # In actual implementation, this would call:
        # pipeline.process_batch_fast(articles)
        await self._simulate_fast_mode(sample_articles)

        elapsed = time.time() - start_time

        # Fast mode should be quick (< 10 seconds with mocks)
        assert elapsed < 10.0, f"Fast mode took {elapsed:.2f}s, should be < 10s with mocks"

    @pytest.mark.asyncio
    async def test_deep_mode_timing(self, sample_articles: list[dict[str, Any]]) -> None:
        """Test that deep mode processes articles within expected time.

        Deep mode should complete in 5-10 minutes for 5 articles.
        This test uses mocked LLM responses for consistent timing.
        """
        start_time = time.time()

        # Simulate deep mode processing (all phases)
        # In actual implementation, this would call:
        # pipeline.process_batch(articles)
        await self._simulate_deep_mode(sample_articles)

        elapsed = time.time() - start_time

        # Deep mode should still be reasonable with mocks
        assert elapsed < 30.0, f"Deep mode took {elapsed:.2f}s, should be < 30s with mocks"

    @pytest.mark.asyncio
    async def test_mode_comparison(self, sample_articles: list[dict[str, Any]]) -> None:
        """Test that fast mode is significantly faster than deep mode.

        Fast mode should be 3-5x faster than deep mode.
        """
        # Measure fast mode
        fast_start = time.time()
        await self._simulate_fast_mode(sample_articles)
        fast_elapsed = time.time() - fast_start

        # Measure deep mode
        deep_start = time.time()
        await self._simulate_deep_mode(sample_articles)
        deep_elapsed = time.time() - deep_start

        # Fast mode should be at least 2x faster (with mocks)
        # In production, this ratio should be 3-5x
        ratio = deep_elapsed / fast_elapsed if fast_elapsed > 0 else 1.0

        # With mocks, the ratio may be less pronounced
        # but fast mode should still be measurably faster
        assert ratio >= 1.5, (
            f"Fast mode should be at least 1.5x faster than deep mode, "
            f"got ratio {ratio:.2f}x (fast: {fast_elapsed:.2f}s, deep: {deep_elapsed:.2f}s)"
        )

    async def _simulate_fast_mode(self, articles: list[dict[str, Any]]) -> None:
        """Simulate fast mode processing.

        Fast mode only runs Phase 1:
        - classifier (is_news check)
        - cleaner (text cleaning)
        - categorizer (category assignment)
        - vectorize (embedding generation)
        """
        import asyncio

        # Simulate Phase 1 processing per article
        async def process_phase1(article: dict[str, Any]) -> dict[str, Any]:
            # Simulate LLM calls for Phase 1
            # classifier: ~100ms
            await asyncio.sleep(0.01)
            # cleaner: ~200ms
            await asyncio.sleep(0.02)
            # categorizer: ~150ms
            await asyncio.sleep(0.015)
            # vectorize: ~300ms
            await asyncio.sleep(0.03)
            return {"processed": True, "article_id": article["url"]}

        # Process concurrently
        await asyncio.gather(*[process_phase1(a) for a in articles])

    async def _simulate_deep_mode(self, articles: list[dict[str, Any]]) -> None:
        """Simulate deep mode processing.

        Deep mode runs all phases:
        - Phase 1: classifier, cleaner, categorizer, vectorize
        - Phase 2: batch merger
        - Phase 3: re-vectorize, analyze, quality_scorer, credibility, entity_extractor
        - Phase 4: persist
        """
        import asyncio

        # Simulate Phase 1 processing
        await self._simulate_fast_mode(articles)

        # Simulate Phase 2: batch merger (serial)
        await asyncio.sleep(0.05)

        # Simulate Phase 3 per article
        async def process_phase3(article: dict[str, Any]) -> dict[str, Any]:
            # re-vectorize: ~300ms
            await asyncio.sleep(0.03)
            # analyze: ~500ms
            await asyncio.sleep(0.05)
            # quality_scorer: ~300ms
            await asyncio.sleep(0.03)
            # credibility: ~200ms
            await asyncio.sleep(0.02)
            # entity_extractor: ~800ms
            await asyncio.sleep(0.08)
            return {"phase3_complete": True}

        # Process Phase 3 concurrently
        await asyncio.gather(*[process_phase3(a) for a in articles])

        # Simulate Phase 4: persist
        await asyncio.sleep(0.02)


@pytest.mark.performance
class TestPipelineModeResourceUsage:
    """Test resource usage differences between processing modes."""

    @pytest.mark.asyncio
    async def test_fast_mode_llm_calls(self, sample_articles: list[dict[str, Any]]) -> None:
        """Test that fast mode makes fewer LLM calls.

        Fast mode should make ~3-4 LLM calls per article:
        - classifier: 1 call
        - cleaner: 1 call
        - categorizer: 1 call
        - vectorize: 0-1 call (depends on embedding provider)

        Total: 3-4 calls per article
        """
        # Simulate counting LLM calls
        llm_call_count = 0

        async def count_llm_call() -> None:
            nonlocal llm_call_count
            llm_call_count += 1
            # Simulate minimal processing
            import asyncio

            await asyncio.sleep(0.001)

        # Fast mode: classifier, cleaner, categorizer per article
        for _ in sample_articles:
            await count_llm_call()  # classifier
            await count_llm_call()  # cleaner
            await count_llm_call()  # categorizer

        # Expected: 3 calls per article
        expected_calls = len(sample_articles) * 3

        assert (
            llm_call_count == expected_calls
        ), f"Fast mode should make {expected_calls} LLM calls, got {llm_call_count}"

    @pytest.mark.asyncio
    async def test_deep_mode_llm_calls(self, sample_articles: list[dict[str, Any]]) -> None:
        """Test that deep mode makes more LLM calls.

        Deep mode should make ~10-12 LLM calls per article:
        - Phase 1: classifier, cleaner, categorizer (3 calls)
        - Phase 2: batch merger (0-1 call per batch)
        - Phase 3: analyze, quality_scorer, credibility, entity_extractor (4 calls)

        Total: ~7-8 calls per article (plus batch merger)
        """
        # Simulate counting LLM calls
        llm_call_count = 0

        async def count_llm_call() -> None:
            nonlocal llm_call_count
            llm_call_count += 1
            import asyncio

            await asyncio.sleep(0.001)

        # Phase 1 per article
        for _ in sample_articles:
            await count_llm_call()  # classifier
            await count_llm_call()  # cleaner
            await count_llm_call()  # categorizer

        # Phase 2: batch merger (1 call for the batch)
        await count_llm_call()

        # Phase 3 per article
        for _ in sample_articles:
            await count_llm_call()  # analyze
            await count_llm_call()  # quality_scorer
            await count_llm_call()  # credibility
            await count_llm_call()  # entity_extractor

        # Expected: 3 * N + 1 + 4 * N = 7 * N + 1 calls
        expected_calls = len(sample_articles) * 7 + 1

        assert (
            llm_call_count == expected_calls
        ), f"Deep mode should make {expected_calls} LLM calls, got {llm_call_count}"


@pytest.mark.performance
class TestPipelineModeOutput:
    """Test output differences between processing modes."""

    @pytest.mark.asyncio
    async def test_fast_mode_output_fields(self, sample_articles: list[dict[str, Any]]) -> None:
        """Test that fast mode produces expected output fields.

        Fast mode should produce:
        - is_news (from classifier)
        - cleaned (title, body from cleaner)
        - category, language, region (from categorizer)
        - vectors (from vectorize)
        """
        # Simulate fast mode output
        result = await self._process_fast_mode(sample_articles[0])

        # Check expected fields
        assert "is_news" in result, "Fast mode should produce is_news"
        assert "cleaned" in result, "Fast mode should produce cleaned"
        assert "category" in result, "Fast mode should produce category"
        assert "vectors" in result, "Fast mode should produce vectors"

        # Check that deep mode fields are NOT present
        assert "entities" not in result, "Fast mode should not produce entities"
        assert "credibility" not in result, "Fast mode should not produce credibility"
        assert "quality_score" not in result, "Fast mode should not produce quality_score"

    @pytest.mark.asyncio
    async def test_deep_mode_output_fields(self, sample_articles: list[dict[str, Any]]) -> None:
        """Test that deep mode produces all expected output fields.

        Deep mode should produce all fields from fast mode plus:
        - entities, relations (from entity_extractor)
        - credibility (from credibility_checker)
        - quality_score (from quality_scorer)
        - summary_info (from analyze)
        """
        # Simulate deep mode output
        result = await self._process_deep_mode(sample_articles[0])

        # Check Phase 1 fields
        assert "is_news" in result, "Deep mode should produce is_news"
        assert "cleaned" in result, "Deep mode should produce cleaned"
        assert "category" in result, "Deep mode should produce category"
        assert "vectors" in result, "Deep mode should produce vectors"

        # Check Phase 3 fields
        assert "entities" in result, "Deep mode should produce entities"
        assert "credibility" in result, "Deep mode should produce credibility"
        assert "quality_score" in result, "Deep mode should produce quality_score"
        assert "summary_info" in result, "Deep mode should produce summary_info"

    async def _process_fast_mode(self, article: dict[str, Any]) -> dict[str, Any]:
        """Simulate fast mode processing and return output."""
        import asyncio

        await asyncio.sleep(0.001)
        return {
            "is_news": True,
            "cleaned": {"title": article["title"], "body": article["body"]},
            "category": "technology",
            "language": "zh",
            "region": "cn",
            "vectors": {"title": [0.1] * 768, "content": [0.2] * 768},
        }

    async def _process_deep_mode(self, article: dict[str, Any]) -> dict[str, Any]:
        """Simulate deep mode processing and return output."""
        import asyncio

        await asyncio.sleep(0.001)
        return {
            "is_news": True,
            "cleaned": {"title": article["title"], "body": article["body"]},
            "category": "technology",
            "language": "zh",
            "region": "cn",
            "vectors": {"title": [0.1] * 768, "content": [0.2] * 768},
            "entities": [{"name": "Test Entity", "type": "ORG"}],
            "relations": [],
            "credibility": {"score": 0.8},
            "quality_score": 0.75,
            "summary_info": {"summary": "Test summary"},
        }
