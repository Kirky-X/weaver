# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for CategorizerNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import CategorizerOutput
from modules.collector.models import ArticleRaw
from modules.processing.nodes.categorizer import (
    CategorizerNode,
    normalize_category,
    normalize_emotion,
)
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    """Create sample raw article."""
    return ArticleRaw(
        url="https://example.com/tech-article",
        title="New AI Model Achieves Breakthrough Performance",
        body="A new artificial intelligence model has demonstrated unprecedented capabilities "
        "in natural language understanding and generation.",
        source="tech_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM client."""
    return AsyncMock()


@pytest.fixture
def mock_prompt_loader():
    """Mock prompt loader."""
    loader = MagicMock()
    loader.get = MagicMock(return_value="Categorizer prompt")
    loader.get_version = MagicMock(return_value="1.5.0")
    return loader


class TestNormalizeCategory:
    """Tests for normalize_category function."""

    def test_normalize_technology_category(self):
        """Test normalizing technology-related categories."""
        assert normalize_category("technology") == "科技"
        assert normalize_category("tech") == "科技"

    def test_normalize_politics_category(self):
        """Test normalizing politics-related categories."""
        assert normalize_category("politics") == "政治"
        assert normalize_category("political") == "政治"

    def test_normalize_economy_category(self):
        """Test normalizing economy-related categories."""
        assert normalize_category("economy") == "经济"
        assert normalize_category("economic") == "经济"
        assert normalize_category("business") == "经济"

    def test_normalize_mixed_case(self):
        """Test that normalization is case-insensitive."""
        assert normalize_category("TECHNOLOGY") == "科技"
        assert normalize_category("Tech") == "科技"
        assert normalize_category("POLITICS") == "政治"

    def test_normalize_empty_string(self):
        """Test that empty string returns default category."""
        assert normalize_category("") == "社会"

    def test_normalize_unknown_category(self):
        """Test that unknown category returns default."""
        assert normalize_category("unknown_category") == "社会"

    def test_normalize_already_chinese(self):
        """Test that Chinese categories are preserved if valid."""
        assert normalize_category("科技") == "科技"
        assert normalize_category("政治") == "政治"

    def test_normalize_invalid_chinese(self):
        """Test that invalid Chinese category returns default."""
        assert normalize_category("未知") == "社会"


class TestNormalizeEmotion:
    """Tests for normalize_emotion function."""

    def test_normalize_optimistic_emotion(self):
        """Test normalizing optimistic emotion."""
        assert normalize_emotion("optimistic") == "乐观"
        assert normalize_emotion("hope") == "期待"

    def test_normalize_negative_emotions(self):
        """Test normalizing negative emotions."""
        assert normalize_emotion("worried") == "担忧"
        assert normalize_emotion("pessimistic") == "悲观"
        assert normalize_emotion("angry") == "愤怒"

    def test_normalize_neutral_emotion(self):
        """Test normalizing neutral emotion."""
        assert normalize_emotion("neutral") == "客观"
        assert normalize_emotion("objective") == "客观"

    def test_normalize_emotion_mixed_case(self):
        """Test that emotion normalization is case-insensitive."""
        assert normalize_emotion("OPTIMISTIC") == "乐观"
        assert normalize_emotion("Neutral") == "客观"

    def test_normalize_emotion_empty_string(self):
        """Test that empty emotion returns default."""
        assert normalize_emotion("") == "客观"

    def test_normalize_emotion_unknown(self):
        """Test that unknown emotion is returned as-is."""
        assert normalize_emotion("unknown_emotion") == "unknown_emotion"


class TestCategorizerNodeBasic:
    """Basic functionality tests for CategorizerNode."""

    @pytest.mark.asyncio
    async def test_categorizer_successful_execution(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test successful categorization with valid LLM response."""
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(
                category="technology",
                language="en",
                region="US",
            )
        )

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify category is normalized
        assert result["category"] == "科技"
        assert result["language"] == "en"
        assert result["region"] == "US"

    @pytest.mark.asyncio
    async def test_categorizer_sets_prompt_version(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test that categorizer records prompt version."""
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="tech", language="zh", region="CN")
        )

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["categorizer"] == "1.5.0"

    @pytest.mark.asyncio
    async def test_categorizer_normalizes_category(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test that categorizer normalizes English categories to Chinese."""
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="politics", language="zh", region="CN")
        )

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "政治"


class TestCategorizerNodeEdgeCases:
    """Edge case tests for CategorizerNode."""

    @pytest.mark.asyncio
    async def test_categorizer_skips_terminal_state(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test that categorizer skips articles in terminal state."""
        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should return state unchanged
        assert "category" not in result
        assert "language" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_categorizer_handles_empty_category(
        self, mock_llm, mock_prompt_loader, sample_raw
    ):
        """Test categorizer with empty category from LLM."""
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="", language="en", region="US")
        )

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should use default category
        assert result["category"] == "社会"

    @pytest.mark.asyncio
    async def test_categorizer_truncates_body(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test that categorizer truncates body to 2000 chars."""
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="tech", language="en", region="US")
        )

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        long_body = "A" * 3000  # Body longer than 2000 chars
        state["cleaned"] = {"title": sample_raw.title, "body": long_body}

        await node.execute(state)

        # Verify LLM was called with truncated body
        call_args = mock_llm.call_at.call_args
        input_data = call_args[0][1]
        assert len(input_data["body"]) == 2000


class TestCategorizerNodeErrorHandling:
    """Error handling tests for CategorizerNode."""

    @pytest.mark.asyncio
    async def test_categorizer_uses_defaults_on_llm_error(
        self, mock_llm, mock_prompt_loader, sample_raw
    ):
        """Test that categorizer uses defaults when LLM fails."""
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM service unavailable"))

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Verify default values are set
        assert result["category"] == "社会"
        assert result["language"] == "en"
        assert result["region"] == "国际"

    @pytest.mark.asyncio
    async def test_categorizer_handles_timeout(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test that categorizer handles timeout errors."""
        import asyncio

        mock_llm.call_at = AsyncMock(side_effect=TimeoutError("Request timeout"))

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should not raise, should use defaults
        assert result["category"] == "社会"
        assert result["language"] == "en"

    @pytest.mark.asyncio
    async def test_categorizer_handles_invalid_response(
        self, mock_llm, mock_prompt_loader, sample_raw
    ):
        """Test that categorizer handles invalid LLM response."""
        mock_llm.call_at = AsyncMock(side_effect=ValueError("Invalid response format"))

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        # Should use defaults
        assert result["category"] == "社会"


class TestCategorizerNodeIntegration:
    """Integration tests for CategorizerNode."""

    @pytest.mark.asyncio
    async def test_categorizer_preserves_state(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test that categorizer preserves existing state fields."""
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="tech", language="zh", region="CN")
        )

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        state["is_news"] = True
        state["existing_field"] = "preserved"

        result = await node.execute(state)

        # Verify existing fields are preserved
        assert result["is_news"] is True
        assert result["existing_field"] == "preserved"
        # And new fields are added
        assert result["category"] == "科技"
        assert result["language"] == "zh"

    @pytest.mark.asyncio
    async def test_categorizer_different_categories(self, mock_llm, mock_prompt_loader, sample_raw):
        """Test categorizer with different category types."""
        test_cases = [
            ("military", "军事"),
            ("economy", "经济"),
            ("society", "社会"),
            ("sports", "体育"),
            ("international", "国际"),
        ]

        for english_cat, expected_chinese in test_cases:
            mock_llm.call_at = AsyncMock(
                return_value=CategorizerOutput(category=english_cat, language="zh", region="CN")
            )

            node = CategorizerNode(mock_llm, mock_prompt_loader)
            state = PipelineState(raw=sample_raw)
            state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

            result = await node.execute(state)
            assert result["category"] == expected_chinese
