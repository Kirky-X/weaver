# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for ClassifierNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import ClassifierOutput
from core.llm.types import CallPoint
from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.classifier import ClassifierNode
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return ArticleRaw(
        url="https://example.com/news-article",
        title="Breaking: Major Scientific Discovery Announced",
        body="Scientists have announced a groundbreaking discovery in quantum computing. "
        "The breakthrough could revolutionize the field of cryptography.",
        source="science_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def sample_non_news_raw():
    """Create sample non-news content."""
    return ArticleRaw(
        url="https://example.com/about-page",
        title="About Us",
        body="This is the about page of our company. We provide excellent services.",
        source="corporate_site",
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
    loader.get = MagicMock(return_value="Classifier prompt")
    loader.get_version = MagicMock(return_value="1.0.0")
    return loader


class TestClassifierNodeBasic:
    """Basic functionality tests for ClassifierNode."""

    @pytest.mark.asyncio
    async def test_classify_news_article(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test classification of a news article."""
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.95))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Verify classification result
        assert result["is_news"] is True
        assert result["terminal"] is False

    @pytest.mark.asyncio
    async def test_classify_non_news_content(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_non_news_raw
    ):
        """Test classification of non-news content."""
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=False, confidence=0.85))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_non_news_raw)

        result = await node.execute(state)

        # Verify classification result
        assert result["is_news"] is False
        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_classify_sets_prompt_version(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that classifier records prompt version in state."""
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.9))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["classifier"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_classify_calls_llm_with_correct_params(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that classifier calls LLM with correct parameters."""
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.9))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        await node.execute(state)

        # Verify LLM was called with correct CallPoint
        mock_llm.call_at.assert_called_once()
        call_args = mock_llm.call_at.call_args
        assert call_args[0][0] == CallPoint.CLASSIFIER

        # Verify input data contains title and body_snippet
        input_data = call_args[0][1]
        assert "title" in input_data
        assert "body_snippet" in input_data
        assert input_data["title"] == sample_raw.title


class TestClassifierNodeEdgeCases:
    """Edge case tests for ClassifierNode."""

    @pytest.mark.asyncio
    async def test_classify_low_confidence_news(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test classification with low confidence score."""
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.55))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Low confidence but still news
        assert result["is_news"] is True
        assert result["terminal"] is False

    @pytest.mark.asyncio
    async def test_classify_high_confidence_non_news(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_non_news_raw
    ):
        """Test classification with high confidence non-news."""
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=False, confidence=0.98))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_non_news_raw)

        result = await node.execute(state)

        # High confidence non-news should set terminal
        assert result["is_news"] is False
        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_classify_with_short_body(self, mock_llm, mock_budget, mock_prompt_loader):
        """Test classification with very short body."""
        short_raw = ArticleRaw(
            url="https://example.com/short",
            title="Short",
            body="Brief",
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=False, confidence=0.7))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=short_raw)

        result = await node.execute(state)

        assert result["is_news"] is False

    @pytest.mark.asyncio
    async def test_classify_with_empty_title(self, mock_llm, mock_budget, mock_prompt_loader):
        """Test classification with empty title."""
        empty_title_raw = ArticleRaw(
            url="https://example.com/no-title",
            title="",
            body="Content without title",
            source="test",
            publish_time=datetime.now(UTC),
            source_host="example.com",
        )

        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=False, confidence=0.6))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=empty_title_raw)

        result = await node.execute(state)

        assert result["is_news"] is False


class TestClassifierNodeErrorHandling:
    """Error handling tests for ClassifierNode."""

    @pytest.mark.asyncio
    async def test_classify_handles_llm_error(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that classifier handles LLM errors by raising exception."""
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM service unavailable"))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        # Classifier should raise the exception (unlike other nodes)
        with pytest.raises(Exception, match="LLM service unavailable"):
            await node.execute(state)

    @pytest.mark.asyncio
    async def test_classify_handles_timeout(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that classifier handles timeout errors."""
        import asyncio

        mock_llm.call_at = AsyncMock(side_effect=TimeoutError("Request timeout"))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        # Should raise the timeout error
        with pytest.raises(asyncio.TimeoutError):
            await node.execute(state)

    @pytest.mark.asyncio
    async def test_classify_handles_invalid_response(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that classifier handles invalid LLM response."""
        mock_llm.call_at = AsyncMock(side_effect=ValueError("Invalid response format"))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        # Should raise the error
        with pytest.raises(ValueError, match="Invalid response format"):
            await node.execute(state)


class TestClassifierNodeIntegration:
    """Integration tests for ClassifierNode."""

    @pytest.mark.asyncio
    async def test_classify_with_token_truncation(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that classifier uses token budget for truncation."""
        mock_budget.truncate = MagicMock(return_value="Truncated body")

        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.9))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        await node.execute(state)

        # Verify truncate was called with correct CallPoint
        mock_budget.truncate.assert_called_once()
        call_args = mock_budget.truncate.call_args
        assert call_args[0][1] == CallPoint.CLASSIFIER

    @pytest.mark.asyncio
    async def test_classify_preserves_raw_data(
        self, mock_llm, mock_budget, mock_prompt_loader, sample_raw
    ):
        """Test that classifier preserves raw data in state."""
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.9))

        node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        # Verify raw data is preserved
        assert result["raw"].url == sample_raw.url
        assert result["raw"].title == sample_raw.title
        assert result["raw"].body == sample_raw.body

    @pytest.mark.asyncio
    async def test_classifier_different_scenarios(self, mock_llm, mock_budget, mock_prompt_loader):
        """Test classifier with different classification scenarios."""
        test_cases = [
            ("Tech News", "Apple announces new iPhone with revolutionary features", True, 0.92),
            ("Sports Update", "Local team wins championship in overtime", True, 0.88),
            ("Corporate About", "We are a leading provider of solutions", False, 0.75),
            ("Navigation Menu", "Home About Contact Services", False, 0.95),
        ]

        for title, body, expected_is_news, confidence in test_cases:
            raw = ArticleRaw(
                url=f"https://example.com/{title.lower().replace(' ', '-')}",
                title=title,
                body=body,
                source="test",
                publish_time=datetime.now(UTC),
                source_host="example.com",
            )

            mock_llm.call_at = AsyncMock(
                return_value=ClassifierOutput(is_news=expected_is_news, confidence=confidence)
            )

            node = ClassifierNode(mock_llm, mock_budget, mock_prompt_loader)
            state = PipelineState(raw=raw)

            result = await node.execute(state)

            assert result["is_news"] == expected_is_news
            assert result["terminal"] == (not expected_is_news)
