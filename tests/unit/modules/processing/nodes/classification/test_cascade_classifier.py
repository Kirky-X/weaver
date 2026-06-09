"""Tests for CascadeClassifierNode — rule-first, LLM fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.validation.output_validator import ClassifierOutput
from modules.ingestion.domain.models import RawArticle
from modules.processing.nodes.classification.classifier import CascadeClassifierNode
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
    async def test_news_keyword_returns_true(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "新华社报道 我国经济持续增长"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is True
        assert result["terminal"] is False

    @pytest.mark.asyncio
    async def test_multiple_news_keywords_return_true(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "据报道，国家发布重要公告"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_non_news_keyword_returns_false(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "登录您的账号"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is False
        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_url_news_pattern_returns_true(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "Random Title"
        sample_raw.url = "https://example.com/news/some-story"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_url_article_pattern_returns_true(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "Random Title"
        sample_raw.url = "https://example.com/article/12345"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_short_title_returns_false(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "Hi"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is False
        assert result["terminal"] is True

    @pytest.mark.asyncio
    async def test_non_news_multiple_keywords_returns_false(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "登录密码 产品介绍"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is False

    @pytest.mark.asyncio
    async def test_single_news_keyword_without_non_news_returns_true(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "刚刚发布的公告"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert result["is_news"] is True

    @pytest.mark.asyncio
    async def test_mixed_keywords_returns_uncertain(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "发布了新的登录"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert "is_news" not in result or result.get("is_news") is True


class TestLLMFallback:
    """LLM fallback for uncertain cases."""

    @pytest.mark.asyncio
    async def test_calls_llm_when_uncertain(self, sample_raw):
        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=True, confidence=0.9))
        mock_budget = MagicMock()
        mock_budget.truncate = MagicMock(return_value="Some body content")
        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get_version = MagicMock(return_value="1.0.0")

        node = CascadeClassifierNode(
            llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader
        )
        sample_raw.title = "Some Ambiguous Title That Needs LLM"
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["is_news"] is True
        mock_llm.call_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_defaults_to_true_when_no_llm(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "Some Ambiguous Title"
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["is_news"] is True
        assert result["terminal"] is False

    @pytest.mark.asyncio
    async def test_uses_llm_result_when_false(self, sample_raw):
        mock_llm = AsyncMock()
        mock_llm.call_at = AsyncMock(return_value=ClassifierOutput(is_news=False, confidence=0.8))
        mock_budget = MagicMock()
        mock_budget.truncate = MagicMock(return_value="body")
        mock_prompt_loader = MagicMock()
        mock_prompt_loader.get_version = MagicMock(return_value="1.0.0")

        node = CascadeClassifierNode(
            llm=mock_llm, budget=mock_budget, prompt_loader=mock_prompt_loader
        )
        sample_raw.title = "Ambiguous"
        state = PipelineState(raw=sample_raw)

        result = await node.execute(state)

        assert result["is_news"] is False
        assert result["terminal"] is True


class TestOutputFormat:
    """Output format compatibility with original ClassifierNode."""

    @pytest.mark.asyncio
    async def test_output_has_is_news_bool(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "报道称经济持续增长"
        state = PipelineState(raw=sample_raw)
        result = await node.execute(state)
        assert isinstance(result["is_news"], bool)
        assert isinstance(result["terminal"], bool)

    @pytest.mark.asyncio
    async def test_state_preserved(self, sample_raw):
        node = CascadeClassifierNode()
        sample_raw.title = "报道称经济持续增长"
        state = PipelineState(raw=sample_raw)
        state["article_id"] = "test-123"
        result = await node.execute(state)
        assert result["article_id"] == "test-123"
        assert result["is_news"] is True
