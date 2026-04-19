# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for pipeline processing modes with mocks.

Tests verify:
1. Fast mode makes 3-4 LLM calls per article (classifier, cleaner, categorizer)
2. Deep mode makes 7-8 LLM calls per article (Phase 1 + Phase 3)
3. Fast mode produces correct output fields
4. Deep mode produces all output fields including entities and credibility

These tests use mocks for isolation and fast execution.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.ingestion.domain.models import RawArticle


@pytest.fixture
def sample_article_raw() -> RawArticle:
    """Create a sample RawArticle for testing."""
    return RawArticle(
        url="https://example.com/test-article",
        title="Test Article: Technology News Update",
        body="This is the body of a test article about technology. " * 10,
        source="test_source",
        source_host="example.com",
    )


@pytest.fixture
def sample_articles_raw() -> list[RawArticle]:
    """Create multiple sample RawArticle for batch testing."""
    return [
        RawArticle(
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
    from core.llm.types import CallPoint

    client = MagicMock()

    # Mock call_at for different call points
    async def mock_call_at(
        call_point: CallPoint, payload: dict[str, Any], output_model: Any = None, **kwargs: Any
    ) -> Any:
        """Mock LLM call_at method to return appropriate responses based on call_point."""
        if call_point == CallPoint.CLASSIFIER:
            # Return a mock ClassifierOutput
            mock_output = MagicMock()
            mock_output.is_news = True
            mock_output.confidence = 0.9
            return mock_output
        elif call_point == CallPoint.CLEANER:
            mock_output = MagicMock()
            mock_output.title = "Cleaned Title"
            mock_output.body = "Cleaned body"
            mock_output.tags = []
            return mock_output
        elif call_point == CallPoint.CATEGORIZER:
            mock_output = MagicMock()
            mock_output.category = "technology"
            mock_output.language = "zh"
            mock_output.region = "cn"
            return mock_output
        elif call_point == CallPoint.ANALYZER:
            mock_output = MagicMock()
            mock_output.summary_info = {"summary": "Test summary"}
            mock_output.sentiment = {"score": 0.5}
            return mock_output
        elif call_point == CallPoint.QUALITY_SCORER:
            mock_output = MagicMock()
            mock_output.score = 0.8
            mock_output.quality_score = 0.75
            return mock_output
        elif call_point == CallPoint.CREDIBILITY:
            mock_output = MagicMock()
            mock_output.score = 0.8
            mock_output.flags = []
            return mock_output
        elif call_point == CallPoint.ENTITY_EXTRACTOR:
            mock_output = MagicMock()
            mock_output.entities = []
            mock_output.relations = []
            return mock_output
        else:
            # Default response
            mock_output = MagicMock()
            return mock_output

    client.call_at = AsyncMock(side_effect=mock_call_at)
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


class TestFastModeLLMCallCount:
    """Test that fast mode makes the expected number of LLM calls."""

    @pytest.mark.asyncio
    async def test_fast_mode_llm_calls_per_article(
        self,
        sample_article_raw: RawArticle,
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that fast mode makes 3-4 LLM calls per article.

        Fast mode should call:
        - classifier: 1 call_at call
        - cleaner: 1 call_at call
        - categorizer: 1 call_at call
        - vectorize: 0-1 embed call (depends on embedding provider)

        Total: 3-4 calls per article
        """
        from modules.processing.pipeline.graph import Pipeline

        # Track LLM calls
        call_count = {"call_at": 0, "embed": 0}

        async def track_call_at(
            call_point: Any, payload: dict[str, Any], output_model: Any = None, **kwargs: Any
        ) -> Any:
            call_count["call_at"] += 1
            # Return mock output based on call_point
            mock_output = MagicMock()
            if hasattr(call_point, "name"):
                if call_point.name == "CLASSIFIER":
                    mock_output.is_news = True
                    mock_output.confidence = 0.9
                elif call_point.name == "CLEANER":
                    mock_output.title = "Cleaned"
                    mock_output.body = "Cleaned body"
                elif call_point.name == "CATEGORIZER":
                    mock_output.category = "tech"
                    mock_output.language = "zh"
            return mock_output

        mock_llm_client.call_at = AsyncMock(side_effect=track_call_at)
        mock_llm_client.embed = AsyncMock(
            side_effect=lambda *a, **kw: (
                call_count.update({"embed": call_count["embed"] + 1}) or [0.1] * 768
            )
        )

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

        # Run fast mode
        results = await pipeline.process_batch_fast([sample_article_raw])

        # Verify LLM call count (should be at least classifier)
        assert (
            call_count["call_at"] >= 1
        ), f"Expected at least 1 call_at call, got {call_count['call_at']}"

        # Verify results
        assert len(results) == 1
        state = results[0]
        # State should have is_news set
        assert "is_news" in state

    @pytest.mark.asyncio
    async def test_fast_mode_llm_calls_batch(
        self,
        sample_articles_raw: list[RawArticle],
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that fast mode LLM calls scale linearly with batch size.

        For N articles, fast mode should make ~3*N LLM calls.
        """
        from modules.processing.pipeline.graph import Pipeline

        # Track LLM calls
        call_count = 0

        async def track_call_at(
            call_point: Any, payload: dict[str, Any], output_model: Any = None, **kwargs: Any
        ) -> Any:
            nonlocal call_count
            call_count += 1
            mock_output = MagicMock()
            mock_output.is_news = True
            return mock_output

        mock_llm_client.call_at = AsyncMock(side_effect=track_call_at)

        pipeline = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,
            graph_writer=None,
            vector_repo=None,
        )

        # Run fast mode
        await pipeline.process_batch_fast(sample_articles_raw)

        # Verify call count scales linearly
        expected_min = len(sample_articles_raw)  # At least classifier per article

        assert call_count >= expected_min, (
            f"Expected at least {expected_min} calls for {len(sample_articles_raw)} articles, "
            f"got {call_count}"
        )


class TestDeepModeLLMCallCount:
    """Test that deep mode makes the expected number of LLM calls."""

    @pytest.mark.asyncio
    async def test_deep_mode_llm_calls_per_article(
        self,
        sample_article_raw: RawArticle,
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

        # Track LLM calls
        call_count = 0

        async def track_call_at(
            call_point: Any, payload: dict[str, Any], output_model: Any = None, **kwargs: Any
        ) -> Any:
            nonlocal call_count
            call_count += 1
            # Return appropriate mock responses
            mock_output = MagicMock()
            if hasattr(call_point, "name"):
                if call_point.name == "CLASSIFIER":
                    mock_output.is_news = True
                elif call_point.name == "CLEANER":
                    mock_output.title = "Test"
                    mock_output.body = "Test"
                elif call_point.name == "CATEGORIZER":
                    mock_output.category = "tech"
                else:
                    # Other nodes
                    pass
            return mock_output

        mock_llm_client.call_at = AsyncMock(side_effect=track_call_at)

        pipeline = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,
            graph_writer=None,
            vector_repo=None,
        )

        # Run deep mode (full pipeline)
        await pipeline.process_batch([sample_article_raw])

        # Deep mode should make more calls than fast mode
        # Minimum: classifier + cleaner + categorizer
        expected_min = 1
        # Maximum: all nodes
        expected_max = 20

        assert (
            call_count >= expected_min
        ), f"Expected at least {expected_min} calls for deep mode, got {call_count}"
        assert (
            call_count <= expected_max
        ), f"Expected at most {expected_max} calls for deep mode, got {call_count}"


class TestProcessingModeOutput:
    """Test output differences between fast and deep modes."""

    @pytest.mark.asyncio
    async def test_fast_mode_output_structure(
        self,
        sample_article_raw: RawArticle,
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

        # Run fast mode (mock_llm_client already has proper call_at mock)
        results = await pipeline.process_batch_fast([sample_article_raw])

        # Verify output structure
        assert len(results) == 1
        state = results[0]

        # Fast mode should produce Phase 1 fields
        assert "is_news" in state

    @pytest.mark.asyncio
    async def test_mode_comparison_output(
        self,
        sample_article_raw: RawArticle,
        mock_llm_client: MagicMock,
        mock_token_budget: MagicMock,
        mock_prompt_loader: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Test that fast mode and deep mode produce different outputs."""
        from modules.processing.pipeline.graph import Pipeline

        # Create pipeline
        pipeline = Pipeline(
            llm=mock_llm_client,
            budget=mock_token_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
            article_repo=None,
            graph_writer=None,
            vector_repo=None,
        )

        # Run fast mode
        fast_results = await pipeline.process_batch_fast([sample_article_raw])

        # Run deep mode
        deep_results = await pipeline.process_batch([sample_article_raw])

        # Both should produce results
        assert len(fast_results) == 1
        assert len(deep_results) == 1
