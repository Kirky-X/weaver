# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for Pipeline workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.collector.models import ArticleRaw
from modules.pipeline.graph import Pipeline
from modules.pipeline.state import PipelineState


@pytest.fixture
def mock_credibility_metrics():
    """Mock credibility metrics to avoid Prometheus mock issues in tests."""
    with patch(
        "modules.pipeline.nodes.credibility_checker.MetricsCollector.credibility_score_dist"
    ) as mock_hist:
        mock_hist.observe = MagicMock()
        yield mock_hist


@pytest.fixture
def sample_raw():
    """Create sample raw article for pipeline testing."""
    return ArticleRaw(
        url="https://example.com/integration-test",
        title="Integration Test Article: AI Breakthrough",
        body="This article tests the complete pipeline flow from raw content to processed output. "
        "It covers multiple stages including classification, cleaning, entity extraction, and analysis.",
        source="test_source",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_budget():
    """Mock token budget manager."""
    budget = MagicMock()
    budget.truncate = lambda text, call_point: text
    return budget


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader."""
    loader = MagicMock()
    loader.get = MagicMock(return_value="Integration test prompt")
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


@pytest.fixture
def mock_event_bus():
    """Mock event bus."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_spacy():
    """Mock spaCy extractor."""
    return MagicMock()


@pytest.fixture
def mock_vector_repo():
    """Mock vector repository."""
    return AsyncMock()


class TestPipelineIntegration:
    """Integration tests for complete pipeline flow."""

    @pytest.mark.asyncio
    async def test_pipeline_processes_raw_article(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, sample_raw
    ):
        """Test that pipeline processes a raw article through all nodes."""
        from core.llm.output_validator import (
            AnalyzeOutput,
            CategorizerOutput,
            ClassifierOutput,
            CleanerContent,
        )

        # Mock LLM responses for different stages using call_at
        mock_llm.call_at = AsyncMock(
            side_effect=[
                ClassifierOutput(is_news=True, confidence=0.95),  # classifier
                CleanerContent(title="Cleaned Title", body="Cleaned body content"),  # cleaner
                CategorizerOutput(category="technology", language="zh", region="CN"),  # categorizer
                AnalyzeOutput(  # analyzer
                    summary="Test summary",
                    event_time=None,
                    subjects=["AI"],
                    key_data=[],
                    impact="Medium",
                    has_data=False,
                    score=0.75,
                    sentiment="positive",
                    sentiment_score=0.6,
                    primary_emotion="optimistic",
                    emotion_targets=[],
                ),
            ]
        )
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.1] * 1024])

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        results = await pipeline.process_batch([sample_raw])

        # Verify pipeline processed the article
        assert len(results) == 1
        result = results[0]
        assert "is_news" in result
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_pipeline_skips_non_news(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, sample_raw
    ):
        """Test that pipeline terminates for non-news content."""
        from core.llm.output_validator import ClassifierOutput

        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=False, confidence=0.90))

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        results = await pipeline.process_batch([sample_raw])
        result = results[0]

        # Verify pipeline marked as terminal
        assert result["terminal"] is True
        assert result["is_news"] is False

    @pytest.mark.asyncio
    async def test_pipeline_preserves_state_through_nodes(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, sample_raw
    ):
        """Test that state is preserved and built up through pipeline nodes."""
        from core.llm.output_validator import (
            AnalyzeOutput,
            CategorizerOutput,
            ClassifierOutput,
            CleanerContent,
        )

        mock_llm.call_at = AsyncMock(
            side_effect=[
                ClassifierOutput(is_news=True, confidence=0.9),
                CleanerContent(title="Clean", body="Body"),
                CategorizerOutput(category="tech", language="zh", region="CN"),
                AnalyzeOutput(
                    summary="Summary",
                    event_time=None,
                    subjects=["Test"],
                    key_data=[],
                    impact="",
                    has_data=False,
                    score=0.7,
                    sentiment="neutral",
                    sentiment_score=0.0,
                    primary_emotion="neutral",
                    emotion_targets=[],
                ),
            ]
        )
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.1] * 1024])

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        results = await pipeline.process_batch([sample_raw])
        result = results[0]

        # Verify new fields are added
        assert "cleaned" in result
        assert "category" in result
        assert "summary_info" in result


class TestPipelineErrorRecovery:
    """Integration tests for pipeline error recovery."""

    @pytest.mark.asyncio
    async def test_pipeline_handles_llm_failure_gracefully(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, sample_raw
    ):
        """Test that pipeline handles LLM failures gracefully."""
        from core.llm.output_validator import ClassifierOutput

        # First call succeeds, second fails
        mock_llm.call_at = AsyncMock(
            side_effect=[
                ClassifierOutput(is_news=True, confidence=0.9),
                Exception("LLM service unavailable"),
            ]
        )

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        # Pipeline should handle the error
        # Depending on implementation, it may raise or continue with defaults
        results = await pipeline.process_batch([sample_raw])
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_pipeline_with_timeout_errors(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, sample_raw
    ):
        """Test pipeline behavior with timeout errors."""
        import asyncio

        from core.llm.output_validator import ClassifierOutput

        mock_llm.call_at = AsyncMock(
            side_effect=[
                TimeoutError("Request timeout"),
            ]
        )

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        # Should either handle timeout or raise
        with pytest.raises((asyncio.TimeoutError, Exception)):
            await pipeline.process_batch([sample_raw])


class TestPipelineDataFlow:
    """Integration tests for data flow through pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_state_accumulates_data(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, sample_raw
    ):
        """Test that state accumulates data from multiple nodes."""
        from core.llm.output_validator import (
            AnalyzeOutput,
            CategorizerOutput,
            ClassifierOutput,
            CleanerContent,
        )

        mock_llm.call_at = AsyncMock(
            side_effect=[
                ClassifierOutput(is_news=True, confidence=0.9),
                CleanerContent(title="T", body="B"),
                CategorizerOutput(category="tech", language="zh", region="CN"),
                AnalyzeOutput(
                    summary="S",
                    event_time=None,
                    subjects=["X"],
                    key_data=[],
                    impact="",
                    has_data=False,
                    score=0.8,
                    sentiment="positive",
                    sentiment_score=0.5,
                    primary_emotion="optimistic",
                    emotion_targets=[],
                ),
            ]
        )
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.1] * 1024])

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        results = await pipeline.process_batch([sample_raw])
        result = results[0]

        # Verify state has accumulated data from multiple stages
        assert "is_news" in result  # From classifier
        assert "cleaned" in result  # From cleaner
        assert "category" in result  # From categorizer
        assert "summary_info" in result  # From analyzer
        assert "sentiment" in result
        assert "score" in result

    @pytest.mark.asyncio
    async def test_pipeline_with_task_id_tracking(
        self, mock_llm, mock_budget, mock_prompt_loader, mock_event_bus, sample_raw
    ):
        """Test that state is properly tracked through pipeline."""
        from core.llm.output_validator import (
            AnalyzeOutput,
            CategorizerOutput,
            ClassifierOutput,
            CleanerContent,
        )

        mock_llm.call_at = AsyncMock(
            side_effect=[
                ClassifierOutput(is_news=True, confidence=0.9),
                CleanerContent(title="T", body="B"),
                CategorizerOutput(category="tech", language="zh", region="CN"),
                AnalyzeOutput(
                    summary="S",
                    event_time=None,
                    subjects=[],
                    key_data=[],
                    impact="",
                    has_data=False,
                    score=0.5,
                    sentiment="neutral",
                    sentiment_score=0.0,
                    primary_emotion="neutral",
                    emotion_targets=[],
                ),
            ]
        )
        mock_llm.embed = AsyncMock(return_value=[[0.1] * 1024, [0.1] * 1024])

        pipeline = Pipeline(
            llm=mock_llm,
            budget=mock_budget,
            prompt_loader=mock_prompt_loader,
            event_bus=mock_event_bus,
        )

        results = await pipeline.process_batch([sample_raw])

        # Pipeline should process successfully and create necessary fields
        assert len(results) == 1
        assert "is_news" in results[0]
        assert "cleaned" in results[0]
        assert "category" in results[0]
