# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for LLM module types."""

import pytest

from core.llm import (
    Capability,
    Label,
    LLMResponse,
    LLMType,
    ModelConfig,
    ProviderConfig,
    RoutingConfig,
    TokenUsage,
)
from core.llm.types import CacheUsage


class TestLabel:
    """Tests for Label parsing."""

    def test_parse_valid_label(self) -> None:
        """Test parsing a valid label string."""
        label = Label.parse("chat.aiping.GLM-4-9B-0414")
        assert label.llm_type == LLMType.CHAT
        assert label.provider == "aiping"
        assert label.model == "GLM-4-9B-0414"

    def test_parse_embedding_label(self) -> None:
        """Test parsing an embedding label."""
        label = Label.parse("embedding.openai.text-embedding-3-large")
        assert label.llm_type == LLMType.EMBEDDING
        assert label.provider == "openai"
        assert label.model == "text-embedding-3-large"

    def test_parse_rerank_label(self) -> None:
        """Test parsing a rerank label."""
        label = Label.parse("rerank.aiping.Qwen3-Reranker-0.6B")
        assert label.llm_type == LLMType.RERANK
        assert label.provider == "aiping"
        assert label.model == "Qwen3-Reranker-0.6B"

    def test_parse_invalid_format(self) -> None:
        """Test parsing invalid format raises error."""
        with pytest.raises(ValueError, match="Invalid label format"):
            Label.parse("invalid_label")

    def test_parse_invalid_type(self) -> None:
        """Test parsing invalid type raises error."""
        with pytest.raises(ValueError, match="Invalid LLM type"):
            Label.parse("invalid.provider.model")

    def test_str_representation(self) -> None:
        """Test string representation."""
        label = Label(llm_type=LLMType.CHAT, provider="aiping", model="GLM-4-9B")
        assert str(label) == "chat.aiping.GLM-4-9B"

    def test_label_frozen(self) -> None:
        """Test that Label is immutable."""
        label = Label(llm_type=LLMType.CHAT, provider="aiping", model="GLM-4-9B")
        with pytest.raises(AttributeError):
            label.provider = "other"  # type: ignore[attr-defined]


class TestModelConfig:
    """Tests for ModelConfig."""

    def test_supports_chat(self) -> None:
        """Test supports method for chat."""
        config = ModelConfig(
            model_id="gpt-4o",
            capabilities=frozenset({Capability.CHAT}),
        )
        assert config.supports(LLMType.CHAT)
        assert not config.supports(LLMType.EMBEDDING)

    def test_supports_multiple_capabilities(self) -> None:
        """Test supports with multiple capabilities."""
        config = ModelConfig(
            model_id="gpt-4o",
            capabilities=frozenset({Capability.CHAT, Capability.VISION}),
        )
        assert config.supports(LLMType.CHAT)
        assert not config.supports(LLMType.EMBEDDING)


class TestProviderConfig:
    """Tests for ProviderConfig."""

    def test_get_model(self) -> None:
        """Test get_model method."""
        chat_model = ModelConfig(model_id="gpt-4o")
        config = ProviderConfig(
            name="openai",
            type="openai",
            api_key="test",
            base_url="https://api.openai.com/v1",
            models={"chat": chat_model},
        )
        assert config.get_model("chat") == chat_model
        assert config.get_model("nonexistent") is None


class TestTokenUsage:
    """Tests for TokenUsage."""

    def test_default_values(self) -> None:
        """Test default values are zero."""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0


class TestCacheUsage:
    """Tests for CacheUsage dataclass."""

    def test_cache_hit_rate_with_values(self) -> None:
        """Test cache_hit_rate returns hit / (hit + miss)."""
        usage = CacheUsage(cache_hit_tokens=100, cache_miss_tokens=50)
        assert usage.cache_hit_rate == pytest.approx(100 / 150)

    def test_cache_hit_rate_zero_division_protection(self) -> None:
        """Test cache_hit_rate returns 0.0 when total is zero (no exception)."""
        usage = CacheUsage()
        assert usage.cache_hit_rate == 0.0

    def test_default_values_are_zero(self) -> None:
        """Test all fields default to 0."""
        usage = CacheUsage()
        assert usage.cache_hit_tokens == 0
        assert usage.cache_miss_tokens == 0
        assert usage.reasoning_tokens == 0

    def test_frozen_immutable(self) -> None:
        """Test CacheUsage is immutable (frozen)."""
        usage = CacheUsage(cache_hit_tokens=10)
        with pytest.raises(AttributeError):
            usage.cache_hit_tokens = 20  # type: ignore[misc]

    def test_full_hit_rate(self) -> None:
        """Test cache_hit_rate returns 1.0 when miss is 0."""
        usage = CacheUsage(cache_hit_tokens=200, cache_miss_tokens=0)
        assert usage.cache_hit_rate == 1.0


class TestLLMResponseCacheFields:
    """Tests for LLMResponse cache field extension."""

    def test_default_cache_fields_are_zero(self) -> None:
        """Test LLMResponse constructs with cache fields defaulting to 0."""
        label = Label(llm_type=LLMType.CHAT, provider="openai", model="gpt-4o")
        response = LLMResponse(
            content="hello",
            label=label,
            latency_ms=100.0,
            token_usage=None,
            model="gpt-4o",
        )
        assert response.cache_hit_tokens == 0
        assert response.cache_miss_tokens == 0

    def test_cache_fields_can_be_set(self) -> None:
        """Test LLMResponse accepts explicit cache field values."""
        label = Label(llm_type=LLMType.CHAT, provider="deepseek", model="deepseek-chat")
        response = LLMResponse(
            content="hello",
            label=label,
            latency_ms=100.0,
            token_usage=None,
            model="deepseek-chat",
            cache_hit_tokens=500,
            cache_miss_tokens=200,
        )
        assert response.cache_hit_tokens == 500
        assert response.cache_miss_tokens == 200

    def test_existing_construction_not_broken(self) -> None:
        """Test existing LLMResponse construction (without cache fields) still works."""
        label = Label(llm_type=LLMType.CHAT, provider="aiping", model="GLM-4-9B")
        token_usage = TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        response = LLMResponse(
            content="result",
            label=label,
            latency_ms=50.0,
            token_usage=token_usage,
            model="GLM-4-9B",
        )
        assert response.content == "result"
        assert response.token_usage is not None
        assert response.token_usage.total_tokens == 15
        assert response.cache_hit_tokens == 0
        assert response.cache_miss_tokens == 0


class TestRoutingConfig:
    """Tests for RoutingConfig."""

    def test_default_fallbacks(self) -> None:
        """Test default fallbacks is empty list."""
        config = RoutingConfig(primary="chat.openai.gpt-4o")
        assert config.fallbacks == []

    def test_with_fallbacks(self) -> None:
        """Test with fallbacks."""
        config = RoutingConfig(
            primary="chat.openai.gpt-4o",
            fallbacks=["chat.anthropic.claude"],
        )
        assert len(config.fallbacks) == 1
