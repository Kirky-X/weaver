# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for AnalyzeNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm import CallPoint
from core.llm.validation.output_validator import AnalyzeOutput
from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.extraction.analyze import AnalyzeNode
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return RawArticle(
        url="https://example.com/article",
        title="AI Breakthrough in Natural Language Processing",
        body="Researchers have achieved a major breakthrough in natural language processing. "
        "The new model demonstrates unprecedented capabilities in understanding context.",
        source="tech_news",
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
    loader.get = MagicMock(return_value="Analyze prompt")
    loader.get_version = MagicMock(return_value="2.1.0")
    return loader


class TestAnalyzeNodeBasic:
    """Basic functionality tests for AnalyzeNode."""

    @pytest.mark.asyncio
    async def test_analyze_successful_execution(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test successful analysis with valid LLM response."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="AI breakthrough in NLP shows unprecedented capabilities",
                event_time="2026-03-18",
                subjects=["AI", "NLP", "Research"],
                key_data=["accuracy: 95%", "model size: 1B parameters"],
                impact="Major advancement in AI field",
                has_data=True,
                score=0.85,
                sentiment="positive",
                sentiment_score=0.7,
                primary_emotion="optimistic",
                emotion_targets=["AI industry", "Researchers"],
            )
        )

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify summary_info is set correctly
        assert "summary_info" in result
        assert (
            result["summary_info"]["summary"]
            == "AI breakthrough in NLP shows unprecedented capabilities"
        )
        assert result["summary_info"]["event_time"] == "2026-03-18"
        assert "AI" in result["summary_info"]["subjects"]
        assert result["summary_info"]["has_data"] is True

        # Verify sentiment is set correctly
        assert "sentiment" in result
        assert result["sentiment"]["sentiment"] == "positive"
        assert result["sentiment"]["sentiment_score"] == 0.7
        assert result["sentiment"]["primary_emotion"] == "乐观"  # Normalized

        # Verify score is set
        assert result["score"] == 0.85

    @pytest.mark.asyncio
    async def test_analyze_sets_prompt_version(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze node records prompt version in state."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
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
            )
        )

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["analyze"] == "2.1.0"

    @pytest.mark.asyncio
    async def test_analyze_calls_llm_with_correct_params(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze calls LLM with correct parameters."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test",
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
            )
        )

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": "Test Title", "body": "Test Body"}

        await node.execute(state)

        # Verify LLM was called with correct CallPoint
        mock_llm.call_at.assert_called_once()
        call_args = mock_llm.call_at.call_args
        assert call_args[0][0] == CallPoint.ANALYZE

        # Verify input data
        input_data = call_args[0][1]
        assert input_data["title"] == "Test Title"
        assert "body" in input_data


class TestAnalyzeNodeEdgeCases:
    """Edge case tests for AnalyzeNode."""

    @pytest.mark.asyncio
    async def test_analyze_skips_terminal_state(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze skips articles in terminal state."""
        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should return state unchanged
        assert "summary_info" not in result
        assert "sentiment" not in result
        assert "score" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_skips_merged_articles(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze skips merged articles."""
        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["is_merged"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should return state unchanged
        assert "summary_info" not in result
        assert "sentiment" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_handles_empty_subjects(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test analysis with empty subjects list."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
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
            )
        )

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["summary_info"]["subjects"] == []


class TestAnalyzeNodeErrorHandling:
    """Error handling tests for AnalyzeNode."""

    @pytest.mark.asyncio
    async def test_analyze_uses_defaults_on_llm_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze uses default values when LLM fails."""
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM service unavailable"))

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify default values are set
        assert result["summary_info"]["summary"] == sample_raw.title
        assert result["summary_info"]["event_time"] is None
        assert result["summary_info"]["subjects"] == []

        assert result["sentiment"]["sentiment"] == "neutral"
        assert result["sentiment"]["sentiment_score"] == 0.0
        assert result["sentiment"]["primary_emotion"] == "客观"

        assert result["score"] == 0.5

    @pytest.mark.asyncio
    async def test_analyze_handles_timeout_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze handles timeout errors gracefully."""
        import asyncio

        mock_llm.call_at = AsyncMock(side_effect=TimeoutError("Request timeout"))

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should not raise, should use defaults
        assert result["score"] == 0.5
        assert result["sentiment"]["sentiment"] == "neutral"

    @pytest.mark.asyncio
    async def test_analyze_handles_invalid_response(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze handles invalid LLM response."""
        mock_llm.call_at = AsyncMock(side_effect=ValueError("Invalid response format"))

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should use defaults
        assert result["score"] == 0.5
        assert "summary_info" in result


class TestAnalyzeNodeIntegration:
    """Integration tests for AnalyzeNode."""

    @pytest.mark.asyncio
    async def test_analyze_with_token_truncation(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze uses token budget for truncation."""
        mock_budget.truncate = MagicMock(return_value="Truncated body text")

        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Summary",
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
            )
        )

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        await node.execute(state)

        # Verify truncate was called with correct CallPoint
        mock_budget.truncate.assert_called_once()
        call_args = mock_budget.truncate.call_args
        assert call_args[0][1] == CallPoint.ANALYZE

    @pytest.mark.asyncio
    async def test_analyze_preserves_state_fields(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that analyze preserves existing state fields."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="",
                has_data=False,
                score=0.8,
                sentiment="positive",
                sentiment_score=0.6,
                primary_emotion="optimistic",
                emotion_targets=[],
            )
        )

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        state["is_news"] = True
        state["existing_field"] = "should_be_preserved"

        result = await node.execute(state)

        # Verify existing fields are preserved
        assert result["is_news"] is True
        assert result["existing_field"] == "should_be_preserved"
        # And new fields are added
        assert "summary_info" in result
        assert "sentiment" in result
        assert result["score"] == 0.8


class TestAnalyzeNodeSKEPIntegration:
    """Tests for SKEP SentimentAnalyzer integration in AnalyzeNode."""

    @pytest.mark.asyncio
    async def test_skep_high_confidence_overrides_llm_sentiment(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """When SKEP returns high confidence, its result overrides LLM sentiment."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="",
                has_data=False,
                score=0.5,
                sentiment="neutral",
                sentiment_score=0.3,
                primary_emotion="neutral",
                emotion_targets=[],
            )
        )

        # Mock SentimentAnalyzer with high-confidence SKEP result
        sentiment_analyzer = AsyncMock()
        sentiment_analyzer.analyze = AsyncMock(
            return_value={
                "sentiment": "positive",
                "sentiment_score": 0.92,
                "source": "skep",
            }
        )

        node = AnalyzeNode(
            mock_llm,
            mock_budget,
            mock_prompt_loader,
            sentiment_analyzer=sentiment_analyzer,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # SKEP result should override LLM sentiment
        assert result["sentiment"]["sentiment"] == "positive"
        assert result["sentiment"]["sentiment_score"] == 0.92
        # LLM summary and score should remain unchanged
        assert result["score"] == 0.5
        assert result["summary_info"]["summary"] == "Test summary"

    @pytest.mark.asyncio
    async def test_skep_low_confidence_keeps_llm_sentiment(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """When SKEP returns low confidence (skep_fallback), LLM sentiment is kept."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="",
                has_data=False,
                score=0.5,
                sentiment="positive",
                sentiment_score=0.7,
                primary_emotion="optimistic",
                emotion_targets=["AI"],
            )
        )

        # Mock SentimentAnalyzer with low-confidence SKEP result (skep_fallback)
        sentiment_analyzer = AsyncMock()
        sentiment_analyzer.analyze = AsyncMock(
            return_value={
                "sentiment": "neutral",
                "sentiment_score": 0.3,
                "source": "skep_fallback",
                "degraded_fields": ["sentiment"],
            }
        )

        node = AnalyzeNode(
            mock_llm,
            mock_budget,
            mock_prompt_loader,
            sentiment_analyzer=sentiment_analyzer,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # LLM sentiment should be kept (not overridden by skep_fallback)
        assert result["sentiment"]["sentiment"] == "positive"
        assert result["sentiment"]["sentiment_score"] == 0.7

    @pytest.mark.asyncio
    async def test_skep_llm_fallback_overrides_llm_sentiment(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """When SKEP falls back to its own LLM call, that result is used."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="",
                has_data=False,
                score=0.5,
                sentiment="neutral",
                sentiment_score=0.3,
                primary_emotion="neutral",
                emotion_targets=[],
            )
        )

        # Mock SentimentAnalyzer with LLM fallback result
        sentiment_analyzer = AsyncMock()
        sentiment_analyzer.analyze = AsyncMock(
            return_value={
                "sentiment": "negative",
                "sentiment_score": 0.8,
                "source": "llm",
            }
        )

        node = AnalyzeNode(
            mock_llm,
            mock_budget,
            mock_prompt_loader,
            sentiment_analyzer=sentiment_analyzer,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # SKEP's LLM fallback result should override pipeline LLM sentiment
        assert result["sentiment"]["sentiment"] == "negative"
        assert result["sentiment"]["sentiment_score"] == 0.8

    @pytest.mark.asyncio
    async def test_no_sentiment_analyzer_uses_llm_sentiment(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Without SentimentAnalyzer, LLM sentiment is used as before."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="",
                has_data=False,
                score=0.5,
                sentiment="positive",
                sentiment_score=0.7,
                primary_emotion="optimistic",
                emotion_targets=[],
            )
        )

        node = AnalyzeNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # LLM sentiment should be used
        assert result["sentiment"]["sentiment"] == "positive"
        assert result["sentiment"]["sentiment_score"] == 0.7

    @pytest.mark.asyncio
    async def test_skep_error_keeps_llm_sentiment(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """When SKEP analysis fails, LLM sentiment is kept."""
        mock_llm.call_at = AsyncMock(
            return_value=AnalyzeOutput(
                summary="Test summary",
                event_time=None,
                subjects=[],
                key_data=[],
                impact="",
                has_data=False,
                score=0.5,
                sentiment="positive",
                sentiment_score=0.7,
                primary_emotion="optimistic",
                emotion_targets=[],
            )
        )

        # Mock SentimentAnalyzer that raises an error
        sentiment_analyzer = AsyncMock()
        sentiment_analyzer.analyze = AsyncMock(side_effect=RuntimeError("SKEP model error"))

        node = AnalyzeNode(
            mock_llm,
            mock_budget,
            mock_prompt_loader,
            sentiment_analyzer=sentiment_analyzer,
        )
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # LLM sentiment should be kept despite SKEP error
        assert result["sentiment"]["sentiment"] == "positive"
        assert result["sentiment"]["sentiment_score"] == 0.7
