# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for LiteLLMCaller.rerank() token usage tracking.

Test 5.1: rerank returns TokenUsage (not None) with input_tokens > 0 and output_tokens == 0.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm.types import Label, LLMType, TokenUsage


def _make_label(provider: str = "cohere", model: str = "rerank-v3") -> Label:
    return Label(llm_type=LLMType.RERANK, provider=provider, model=model)


@pytest.mark.asyncio
class TestRerankTokenUsage:
    """Verify rerank returns proper TokenUsage."""

    async def test_rerank_returns_token_usage_not_none(self):
        """rerank() must return LLMResponse with token_usage as TokenUsage instance."""
        from core.llm.caller import LITELLM_RERANK_PROVIDERS, LiteLLMCaller

        caller = LiteLLMCaller()
        label = _make_label(provider="cohere", model="rerank-v3")

        mock_response = MagicMock()
        mock_response.results = [
            MagicMock(index=0, relevance_score=0.9),
            MagicMock(index=1, relevance_score=0.7),
        ]

        with patch("core.llm.caller.arerank", new_callable=AsyncMock, return_value=mock_response):
            with patch("core.llm.caller.token_counter", return_value=42):
                result = await caller.rerank(
                    label=label,
                    provider_type="cohere",
                    api_key="test-key",
                    api_base="",
                    query="test query",
                    documents=["doc1", "doc2"],
                    top_n=2,
                )

        assert result.token_usage is not None
        assert isinstance(result.token_usage, TokenUsage)

    async def test_rerank_input_tokens_positive(self):
        """rerank() must set input_tokens > 0 (estimated from text)."""
        from core.llm.caller import LiteLLMCaller

        caller = LiteLLMCaller()
        label = _make_label(provider="cohere", model="rerank-v3")

        mock_response = MagicMock()
        mock_response.results = [MagicMock(index=0, relevance_score=0.95)]

        with patch("core.llm.caller.arerank", new_callable=AsyncMock, return_value=mock_response):
            with patch("core.llm.caller.token_counter", return_value=123):
                result = await caller.rerank(
                    label=label,
                    provider_type="cohere",
                    api_key="test-key",
                    api_base="",
                    query="search query",
                    documents=["document one", "document two"],
                    top_n=1,
                )

        assert result.token_usage.input_tokens > 0
        assert result.token_usage.input_tokens == 123

    async def test_rerank_output_tokens_zero(self):
        """rerank() must set output_tokens == 0 (rerank produces no output tokens)."""
        from core.llm.caller import LiteLLMCaller

        caller = LiteLLMCaller()
        label = _make_label(provider="cohere", model="rerank-v3")

        mock_response = MagicMock()
        mock_response.results = []

        with patch("core.llm.caller.arerank", new_callable=AsyncMock, return_value=mock_response):
            with patch("core.llm.caller.token_counter", return_value=50):
                result = await caller.rerank(
                    label=label,
                    provider_type="cohere",
                    api_key="test-key",
                    api_base="",
                    query="query",
                    documents=["doc"],
                    top_n=1,
                )

        assert result.token_usage.output_tokens == 0

    async def test_rerank_total_tokens_equals_input(self):
        """rerank() total_tokens == input_tokens since output is 0."""
        from core.llm.caller import LiteLLMCaller

        caller = LiteLLMCaller()
        label = _make_label(provider="cohere", model="rerank-v3")

        mock_response = MagicMock()
        mock_response.results = [MagicMock(index=0, relevance_score=0.8)]

        with patch("core.llm.caller.arerank", new_callable=AsyncMock, return_value=mock_response):
            with patch("core.llm.caller.token_counter", return_value=200):
                result = await caller.rerank(
                    label=label,
                    provider_type="cohere",
                    api_key="test-key",
                    api_base="",
                    query="q",
                    documents=["d1", "d2"],
                )

        assert result.token_usage.total_tokens == result.token_usage.input_tokens
        assert result.token_usage.total_tokens == 200

    async def test_rerank_token_counter_fallback_uses_word_count(self):
        """When token_counter raises, rerank falls back to word count."""
        from core.llm.caller import LiteLLMCaller

        caller = LiteLLMCaller()
        label = _make_label(provider="cohere", model="rerank-v3")

        mock_response = MagicMock()
        mock_response.results = []

        with patch("core.llm.caller.arerank", new_callable=AsyncMock, return_value=mock_response):
            with patch(
                "core.llm.caller.token_counter",
                side_effect=Exception("model not supported"),
            ):
                result = await caller.rerank(
                    label=label,
                    provider_type="cohere",
                    api_key="test-key",
                    api_base="",
                    query="one two three",
                    documents=["four five"],
                )

        # "one two three four five" = 5 words
        assert result.token_usage.input_tokens == 5
        assert result.token_usage.output_tokens == 0

    async def test_rerank_openai_compatible_returns_token_usage(self):
        """OpenAI-compatible rerank path also returns TokenUsage."""
        from core.llm.caller import LiteLLMCaller

        caller = LiteLLMCaller()
        label = _make_label(provider="aiping", model="rerank-model")

        with patch.object(
            caller,
            "_rerank_openai_compatible",
            new_callable=AsyncMock,
            return_value=[{"index": 0, "score": 0.85}],
        ):
            with patch("core.llm.caller.token_counter", return_value=300):
                result = await caller.rerank(
                    label=label,
                    provider_type="aiping",
                    api_key="test-key",
                    api_base="https://api.aiping.cn/v1",
                    query="query text",
                    documents=["doc1"],
                    top_n=1,
                )

        assert result.token_usage is not None
        assert isinstance(result.token_usage, TokenUsage)
        assert result.token_usage.input_tokens == 300
        assert result.token_usage.output_tokens == 0
