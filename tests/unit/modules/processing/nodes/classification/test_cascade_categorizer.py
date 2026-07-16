# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

"""Tests for CascadeCategorizerNode — rule-first, LLM fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.validation.output_validator import CategorizerOutput
from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.classification.categorizer import (
    CascadeCategorizerNode,
    normalize_category,
    normalize_emotion,
)
from modules.processing.pipeline.state import PipelineState


@pytest.fixture
def sample_raw():
    return RawArticle(
        url="https://example.com/article",
        title="Test Article",
        body="Some body content",
        source="test",
        publish_time=datetime.now(UTC),
        source_host="example.com",
    )


class TestRuleLayer:
    """Rule layer: must classify without LLM call."""

    @pytest.mark.asyncio
    async def test_economy_keywords(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "今日股市大涨 央行降息"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["category"] == "经济"

    @pytest.mark.asyncio
    async def test_military_keywords(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "国防部发布军事演习公告"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["category"] == "军事"

    @pytest.mark.asyncio
    async def test_tech_keywords(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "AI人工智能芯片取得重大突破"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["category"] == "科技"

    @pytest.mark.asyncio
    async def test_sports_keywords(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "中国队在奥运会上夺得冠军"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["category"] == "体育"

    @pytest.mark.asyncio
    async def test_politics_keywords(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "全国人大会议通过重要立法"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["category"] == "政治"

    @pytest.mark.asyncio
    async def test_multiple_keywords_same_category(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "GDP数据利好 央行降息预期升温"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["category"] == "经济"

    @pytest.mark.asyncio
    async def test_no_llm_called_when_rule_matches(self, sample_raw):
        mock_llm = AsyncMock()
        node = CascadeCategorizerNode(llm=mock_llm)
        sample_raw.title = "股市大盘分析"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        await node.execute(state)
        mock_llm.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_default_language_with_chinese_title(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "股市大涨"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["language"] == "zh"
        # Region is inferred from source_host, not hardcoded from title
        # example.com → "国际" (no .cn TLD)
        assert result["region"] == "国际"

    @pytest.mark.asyncio
    async def test_sets_default_language_with_english_title(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "Stock Market Rises Sharply"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert result["language"] == "en"
        assert result["region"] == "国际"


class TestLLMFallback:
    """LLM fallback for uncertain cases."""

    @pytest.mark.asyncio
    async def test_calls_llm_when_uncertain(self, sample_raw):
        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="technology", language="en", region="US")
        )
        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get_version = MagicMock(return_value="1.5.0")

        node = CascadeCategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)
        sample_raw.title = "New Development in Computing"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "科技"
        mock_llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_defaults_when_no_llm(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "Some Unclear Topic"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"
        assert result["language"] == "en"
        assert result["region"] == "国际"

    @pytest.mark.asyncio
    async def test_defaults_when_no_llm_chinese_title(self, sample_raw):
        """Chinese title with no LLM must fall back to 'zh', not 'en'."""
        node = CascadeCategorizerNode()
        sample_raw.title = "某不明主题事件"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"
        assert result["language"] == "zh"
        assert result["region"] == "国际"

    @pytest.mark.asyncio
    async def test_defaults_on_llm_error(self, sample_raw):
        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))
        mock_prompt_loader = MagicMock()

        node = CascadeCategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)
        sample_raw.title = "Some Unclear Topic"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"
        assert result["language"] == "en"
        assert result["region"] == "国际"

    @pytest.mark.asyncio
    async def test_defaults_on_llm_error_chinese_title(self, sample_raw):
        """Chinese title on LLM error must fall back to 'zh', not 'en'.

        Regression: previously hard-coded 'en' mislabeled 20 Chinese
        articles from chinanews as English.
        """
        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(side_effect=Exception("LLM unavailable"))
        mock_prompt_loader = MagicMock()

        node = CascadeCategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)
        sample_raw.title = "广州某地发生重大事件"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert result["category"] == "社会"
        assert result["language"] == "zh"
        assert result["region"] == "国际"
        assert "language" in result.get("degraded_fields", [])

    @pytest.mark.asyncio
    async def test_records_prompt_version_on_llm_call(self, sample_raw):
        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(
            return_value=CategorizerOutput(category="tech", language="zh", region="CN")
        )
        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get_version = MagicMock(return_value="1.5.0")

        node = CascadeCategorizerNode(llm=mock_llm, prompt_loader=mock_prompt_loader)
        sample_raw.title = "New Computing Platform"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert "prompt_versions" in result
        assert result["prompt_versions"]["categorizer"] == "1.5.0"


class TestTerminalState:
    """Skip execution for terminal states."""

    @pytest.mark.asyncio
    async def test_skips_terminal_state(self, sample_raw):
        mock_llm = AsyncMock()
        node = CascadeCategorizerNode(llm=mock_llm)
        state = PipelineState(raw=sample_raw)
        state["terminal"] = True
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}

        result = await node.execute(state)

        assert "category" not in result
        mock_llm.call_at.assert_not_called()


class TestOutputFormat:
    """Output format compatibility with original CategorizerNode."""

    @pytest.mark.asyncio
    async def test_output_has_category_string(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "股市大涨"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        result = await node.execute(state)
        assert isinstance(result["category"], str)

    @pytest.mark.asyncio
    async def test_state_preserved(self, sample_raw):
        node = CascadeCategorizerNode()
        sample_raw.title = "军事演习"
        state = PipelineState(raw=sample_raw)
        state["cleaned"] = {"title": sample_raw.title, "body": sample_raw.body}
        state["is_news"] = True
        state["existing"] = "preserved"
        result = await node.execute(state)
        assert result["is_news"] is True
        assert result["existing"] == "preserved"
