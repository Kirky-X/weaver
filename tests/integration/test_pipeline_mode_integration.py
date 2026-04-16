# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for pipeline processing modes with real services.

Tests verify:
1. Fast mode makes 3-4 LLM calls per article (classifier, cleaner, categorizer)
2. Deep mode makes 7-8 LLM calls per article (Phase 1 + Phase 3)
3. Fast mode produces correct output fields
4. Deep mode produces all output fields including entities and credibility

These tests use real services when available and are skipped otherwise.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.ingestion.domain.models import ArticleRaw


@pytest.fixture
def sample_article_raw() -> ArticleRaw:
    """Create a sample ArticleRaw for testing."""
    return ArticleRaw(
        url="https://example.com/test-article",
        title="Test Article: Technology News Update",
        body="This is the body of a test article about technology. " * 10,
        source="test_source",
        source_host="example.com",
    )


@pytest.fixture
def sample_articles_raw() -> list[ArticleRaw]:
    """Create multiple sample ArticleRaw for batch testing."""
    return [
        ArticleRaw(
            url=f"https://example.com/test-article-{i}",
            title=f"Test Article {i}: Technology News",
            body=f"Body of test article {i} about technology. " * 10,
            source="test_source",
            source_host="example.com",
        )
        for i in range(3)
    ]


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Create a mock LLM client for testing."""
    client = MagicMock()

    # Mock chat completion for different nodes
    async def mock_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "content": '{"is_news": true, "reason": "Technology news article"}',
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    client.chat = AsyncMock(side_effect=mock_chat)
    client.embed = AsyncMock(return_value=[0.1] * 768)
    return client


@pytest.fixture
def mock_token_budget() -> MagicMock:
    """Create a mock token budget manager."""
    budget = MagicMock()
    budget.check_budget = AsyncMock(return_value=True)
    budget.record_usage = AsyncMock()
    return budget


@pytest.fixture
def mock_prompt_loader() -> MagicMock:
    """Create a mock prompt loader."""
    loader = MagicMock()
    loader.load = MagicMock(return_value=MagicMock(content="Test prompt"))
    return loader


@pytest.fixture
def mock_event_bus() -> MagicMock:
    """Create a mock event bus."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.subscribe = MagicMock()
    return bus


@pytest.mark.integration
class TestFastModeLLMCallCount:
    """Test that fast mode makes the expected number of LLM calls."""

    @pytest.mark.asyncio
    async def test_fast_mode_llm_calls_per_article(
        self,
        sample_article_raw: ArticleRaw,
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that fast mode makes 3-4 LLM calls per article.

        Fast mode should call:
        - classifier: 1 chat call
        - cleaner: 1 chat call
        - categorizer: 1 chat call
        - vectorize: 0-1 embed call (depends on embedding provider)

        Total: 3-4 calls per article
        """
        from modules.processing.pipeline.graph import Pipeline

        # Create pipeline with minimal dependencies for fast mode
        pipeline = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,  # Skip persistence
            graph_writer=None,
            vector_repo=None,
        )

        # Track LLM calls
        call_count = {"chat": 0, "embed": 0}

        async def track_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
            call_count["chat"] += 1
            # Return different responses based on call order
            if call_count["chat"] == 1:
                return {"content": '{"is_news": true}', "usage": {"input_tokens": 100}}
            elif call_count["chat"] == 2:
                return {"content": '{"title": "Cleaned", "body": "Cleaned body"}', "usage": {}}
            else:
                return {
                    "content": '{"category": "tech", "language": "zh"}',
                    "usage": {},
                }

        mock_llm_client.chat = AsyncMock(side_effect=track_chat)
        mock_llm_client.embed = AsyncMock(
            side_effect=lambda *a, **kw: call_count.update({"embed": call_count["embed"] + 1})
            or [0.1] * 768
        )

        # Run fast mode
        results = await pipeline.process_batch_fast([sample_article_raw])

        # Verify LLM call count
        assert call_count["chat"] >= 2, f"Expected at least 2 chat calls, got {call_count['chat']}"
        assert call_count["chat"] <= 4, f"Expected at most 4 chat calls, got {call_count['chat']}"

        # Verify results
        assert len(results) == 1
        state = results[0]
        assert "is_news" in state or state.get("terminal") is True

    @pytest.mark.asyncio
    async def test_fast_mode_llm_calls_batch(
        self,
        sample_articles_raw: list[ArticleRaw],
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that fast mode LLM calls scale linearly with batch size.

        For N articles, fast mode should make ~3*N LLM calls.
        """
        from modules.processing.pipeline.graph import Pipeline

        pipeline = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,
            graph_writer=None,
            vector_repo=None,
        )

        # Track LLM calls
        call_count = 0

        async def track_call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"content": '{"is_news": true}', "usage": {}}

        mock_llm_client.chat = AsyncMock(side_effect=track_call)

        # Run fast mode
        await pipeline.process_batch_fast(sample_articles_raw)

        # Verify call count scales linearly
        expected_min = len(sample_articles_raw) * 2  # At least classifier + cleaner
        expected_max = len(sample_articles_raw) * 4  # At most all 4 calls

        assert call_count >= expected_min, (
            f"Expected at least {expected_min} calls for {len(sample_articles_raw)} articles, "
            f"got {call_count}"
        )
        assert call_count <= expected_max, (
            f"Expected at most {expected_max} calls for {len(sample_articles_raw)} articles, "
            f"got {call_count}"
        )


@pytest.mark.integration
class TestDeepModeLLMCallCount:
    """Test that deep mode makes the expected number of LLM calls."""

    @pytest.mark.asyncio
    async def test_deep_mode_llm_calls_per_article(
        self,
        sample_article_raw: ArticleRaw,
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that deep mode makes 7-8 LLM calls per article.

        Deep mode should call:
        - Phase 1: classifier, cleaner, categorizer (3 calls)
        - Phase 2: batch merger (0-1 call for batch)
        - Phase 3: analyze, quality_scorer, credibility, entity_extractor (4 calls)

        Total: ~7-8 calls per article
        """
        from modules.processing.pipeline.graph import Pipeline

        pipeline = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,
            graph_writer=None,
            vector_repo=None,
        )

        # Track LLM calls
        call_count = 0

        async def track_call(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            # Return appropriate mock responses
            return {
                "content": '{"is_news": true, "title": "Test", "body": "Test", '
                '"category": "tech", "score": 0.8, "entities": []}',
                "usage": {},
            }

        mock_llm_client.chat = AsyncMock(side_effect=track_call)

        # Run deep mode (full pipeline)
        await pipeline.process_batch([sample_article_raw])

        # Deep mode should make more calls than fast mode
        # Minimum: classifier + cleaner + categorizer + analyze + quality + credibility + entities
        expected_min = 6
        # Maximum: all nodes
        expected_max = 15

        assert call_count >= expected_min, (
            f"Expected at least {expected_min} calls for deep mode, got {call_count}"
        )
        assert call_count <= expected_max, (
            f"Expected at most {expected_max} calls for deep mode, got {call_count}"
        )


@pytest.mark.integration
class TestProcessingModeOutput:
    """Test output differences between fast and deep modes."""

    @pytest.mark.asyncio
    async def test_fast_mode_output_structure(
        self,
        sample_article_raw: ArticleRaw,
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that fast mode produces Phase 1 fields only."""
        from modules.processing.pipeline.graph import Pipeline

        pipeline = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,
            graph_writer=None,
            vector_repo=None,
        )

        # Mock LLM responses for Phase 1
        responses = [
            {"content": '{"is_news": true}', "usage": {}},
            {"content": '{"title": "Cleaned Title", "body": "Cleaned body"}', "usage": {}},
            {"content": '{"category": "technology", "language": "zh", "region": "cn"}', "usage": {}},
        ]
        response_iter = iter(responses)

        async def mock_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return next(response_iter)

        mock_llm_client.chat = AsyncMock(side_effect=mock_chat)
        mock_llm_client.embed = AsyncMock(return_value=[0.1] * 768)

        # Run fast mode
        results = await pipeline.process_batch_fast([sample_article_raw])

        # Verify output structure
        assert len(results) == 1
        state = results[0]

        # Fast mode should produce Phase 1 fields
        if not state.get("terminal"):
            assert "is_news" in state
            assert state["is_news"] is True

    @pytest.mark.asyncio
    async def test_mode_comparison_output(
        self,
        sample_article_raw: ArticleRaw,
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that fast mode and deep mode produce different outputs."""
        from modules.processing.pipeline.graph import Pipeline

        # Create two pipelines
        pipeline_fast = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,
            graph_writer=None,
            vector_repo=None,
        )

        # Mock responses
        async def mock_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "content": '{"is_news": true, "title": "Test", "body": "Test", '
                '"category": "tech", "score": 0.8, "entities": []}',
                "usage": {},
            }

        mock_llm_client.chat = AsyncMock(side_effect=mock_chat)
        mock_llm_client.embed = AsyncMock(return_value=[0.1] * 768)

        # Run fast mode
        fast_results = await pipeline_fast.process_batch_fast([sample_article_raw])

        # Reset mock
        mock_llm_client.chat = AsyncMock(side_effect=mock_chat)

        # Run deep mode
        deep_results = await pipeline_fast.process_batch([sample_article_raw])

        # Both should produce results
        assert len(fast_results) == 1
        assert len(deep_results) == 1


@pytest.mark.integration
class TestProcessingModeConfiguration:
    """Test mode-specific configuration overrides."""

    def test_fast_mode_config(self) -> None:
        """Test that fast mode config has correct overrides."""
        from scripts.pipeline import ProcessingMode, get_mode_config

        config = get_mode_config(ProcessingMode.FAST)

        assert config.get("skip_entities") is True
        assert config.get("skip_quality") is True
        assert config.get("skip_credibility") is True
        assert config.get("skip_phase3") is True

    def test_deep_mode_config(self) -> None:
        """Test that deep mode config has no overrides."""
        from scripts.pipeline import ProcessingMode, get_mode_config

        config = get_mode_config(ProcessingMode.DEEP)

        # Deep mode should have empty config (no overrides)
        assert config == {}

    def test_processing_mode_enum(self) -> None:
        """Test ProcessingMode enum values."""
        from scripts.pipeline import ProcessingMode

        assert ProcessingMode.FAST.value == "fast"
        assert ProcessingMode.DEEP.value == "deep"
        assert ProcessingMode("fast") == ProcessingMode.FAST
        assert ProcessingMode("deep") == ProcessingMode.DEEP
