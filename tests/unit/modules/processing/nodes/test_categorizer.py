# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for processing CategorizerNode."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.output_validator import CategorizerOutput
from modules.ingestion.domain.models import ArticleRaw
from modules.processing.nodes.categorizer import (
    CategorizerNode,
    normalize_category,
    normalize_emotion,
)
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return ArticleRaw(
        url="https://example.com/tech-article",
        title="New AI Model Achieves Breakthrough Performance",
        body="A new artificial intelligence model has demonstrated unprecedented capabilities.",
        source="tech_news",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_prompt_loader():
    loader = MagicMock()
    loader.get = MagicMock(return_value="Categorizer prompt")
    loader.get_version = MagicMock(return_value="1.5.0")
    return loader


class TestNormalizeCategory:
    def test_normalize_technology(self):
        assert normalize_category("technology") == "科技"
        assert normalize_category("tech") == "科技"

    def test_normalize_politics(self):
        assert normalize_category("politics") == "政治"
        assert normalize_category("political") == "政治"

    def test_normalize_economy(self):
        assert normalize_category("economy") == "经济"
        assert normalize_category("economic") == "经济"
        assert normalize_category("business") == "经济"

    def test_mixed_case(self):
        assert normalize_category("TECHNOLOGY") == "科技"
        assert normalize_category("Tech") == "科技"

    def test_empty_string(self):
        assert normalize_category("") == "社会"

    def test_unknown_category(self):
        assert normalize_category("unknown_category") == "社会"

    def test_already_chinese(self):
        assert normalize_category("科技") == "科技"
        assert normalize_category("政治") == "政治"

    def test_invalid_chinese(self):
        assert normalize_category("未知") == "社会"


class TestNormalizeEmotion:
    def test_optimistic(self):
        assert normalize_emotion("optimistic") == "乐观"
        assert normalize_emotion("hope") == "期待"

    def test_negative(self):
        assert normalize_emotion("worried") == "担忧"
        assert normalize_emotion("pessimistic") == "悲观"
        assert normalize_emotion("angry") == "愤怒"

    def test_neutral(self):
        assert normalize_emotion("neutral") == "客观"
        assert normalize_emotion("objective") == "客观"

    def test_mixed_case(self):
        assert normalize_emotion("OPTIMISTIC") == "乐观"

    def test_empty_string(self):
        assert normalize_emotion("") == "客观"

    def test_unknown(self):
        assert normalize_emotion("unknown_emotion") == "unknown_emotion"


class TestCategorizerNodeBasic:
    @pytest.mark.asyncio
    async def test_successful_execution(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="technology", language="en", region="US")
        )
        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "科技"
        assert result["language"] == "en"
        assert result["region"] == "US"

    @pytest.mark.asyncio
    async def test_sets_prompt_version(self, mock_llm, mock_prompt_loader, sample_raw):
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
    async def test_normalizes_category(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="politics", language="zh", region="CN")
        )
        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "政治"


class TestCategorizerNodeEdgeCases:
    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, mock_llm, mock_prompt_loader, sample_raw):
        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert "category" not in result
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_category(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="", language="en", region="US")
        )
        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"

    @pytest.mark.asyncio
    async def test_truncates_body(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="tech", language="en", region="US")
        )
        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        long_body = "A" * 3000
        state["cleaned"] = {"title": sample_raw.title, "body": long_body}

        await node.execute(state)

        call_args = mock_llm.call_at.call_args
        input_data = call_args[0][1]
        assert len(input_data["body"]) == 2000


class TestCategorizerNodeErrorHandling:
    @pytest.mark.asyncio
    async def test_uses_defaults_on_llm_error(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"
        assert result["language"] == "en"
        assert result["region"] == "国际"

    @pytest.mark.asyncio
    async def test_handles_timeout(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(side_effect=TimeoutError("Request timeout"))

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"

    @pytest.mark.asyncio
    async def test_handles_invalid_response(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(side_effect=ValueError("Invalid response"))

        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"


class TestCategorizerNodeIntegration:
    @pytest.mark.asyncio
    async def test_preserves_state(self, mock_llm, mock_prompt_loader, sample_raw):
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="tech", language="zh", region="CN")
        )
        node = CategorizerNode(mock_llm, mock_prompt_loader)
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        state["is_news"] = True
        state["existing_field"] = "preserved"

        result = await node.execute(state)

        assert result["is_news"] is True
        assert result["existing_field"] == "preserved"
        assert result["category"] == "科技"

    @pytest.mark.asyncio
    async def test_different_categories(self, mock_llm, mock_prompt_loader, sample_raw):
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
