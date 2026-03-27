# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for the new LLM label-based architecture."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.label import InvalidLabelError, Label
from core.llm.pool_manager import AllProvidersFailedError, PoolManagerConfig, ProviderPoolManager
from core.llm.provider_pool import CircuitOpenError, ProviderPool
from core.llm.registry import ProviderInstanceConfig, ProviderNotFoundError, ProviderRegistry
from core.llm.request import LLMRequest, LLMResponse, ProviderMetrics
from core.llm.router import LabelRouter, RoutingStrategy
from core.llm.types import LLMType


class TestLabel:
    """Tests for Label parsing."""

    def test_parse_valid_chat_label(self):
        """Test parsing a valid chat label."""
        label = Label.parse("chat.openai.gpt-4o")
        assert label.llm_type == LLMType.CHAT
        assert label.provider == "openai"
        assert label.model == "gpt-4o"

    def test_parse_valid_embedding_label(self):
        """Test parsing a valid embedding label."""
        label = Label.parse("embedding.aiping.Qwen3-Embedding-0.6B")
        assert label.llm_type == LLMType.EMBEDDING
        assert label.provider == "aiping"
        assert label.model == "Qwen3-Embedding-0.6B"

    def test_parse_valid_rerank_label(self):
        """Test parsing a valid rerank label."""
        label = Label.parse("rerank.jina.jina-reranker-v2")
        assert label.llm_type == LLMType.RERANK
        assert label.provider == "jina"
        assert label.model == "jina-reranker-v2"

    def test_parse_invalid_format_too_few_parts(self):
        """Test parsing an invalid label with too few parts."""
        with pytest.raises(InvalidLabelError):
            Label.parse("invalid")

    def test_parse_invalid_format_invalid_type(self):
        """Test parsing a label with invalid type."""
        with pytest.raises(InvalidLabelError):
            Label.parse("invalid.provider.model")

    def test_str_representation(self):
        """Test string representation of label."""
        label = Label.parse("chat.openai.gpt-4o")
        assert str(label) == "chat.openai.gpt-4o"


class TestProviderMetrics:
    """Tests for ProviderMetrics."""

    def test_initial_metrics(self):
        """Test initial metrics values."""
        metrics = ProviderMetrics()
        assert metrics.total_requests == 0
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 0
        assert metrics.success_rate == 1.0  # No requests = 100% success
        assert metrics.avg_latency_ms == 0.0

    def test_record_success(self):
        """Test recording successful requests."""
        metrics = ProviderMetrics()
        metrics.record_success(100.0)
        metrics.record_success(200.0)

        assert metrics.total_requests == 2
        assert metrics.successful_requests == 2
        assert metrics.failed_requests == 0
        assert metrics.success_rate == 1.0
        assert metrics.avg_latency_ms == 150.0

    def test_record_failure(self):
        """Test recording failed requests."""
        metrics = ProviderMetrics()
        metrics.record_failure("TimeoutError")

        assert metrics.total_requests == 1
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 1
        assert metrics.success_rate == 0.0
        assert metrics.last_error == "TimeoutError"

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        metrics = ProviderMetrics()
        metrics.record_success(100.0)
        metrics.record_success(100.0)
        metrics.record_failure("Error")

        assert metrics.total_requests == 3
        assert metrics.success_rate == 2 / 3


class TestLLMRequest:
    """Tests for LLMRequest."""

    def test_request_creation(self):
        """Test creating an LLM request."""
        label = Label.parse("chat.openai.gpt-4o")
        request = LLMRequest(
            label=label,
            payload={"prompt": "test"},
        )

        assert request.label == label
        assert request.payload == {"prompt": "test"}
        assert request.priority == 5

    def test_request_priority_sorting(self):
        """Test request priority sorting."""
        label = Label.parse("chat.openai.gpt-4o")

        request_high = LLMRequest(label=label, payload={}, priority=1)
        request_low = LLMRequest(label=label, payload={}, priority=10)

        assert request_high < request_low


class TestLLMResponse:
    """Tests for LLMResponse."""

    def test_response_creation(self):
        """Test creating an LLM response."""
        label = Label.parse("chat.openai.gpt-4o")
        response = LLMResponse(
            content="Hello, world!",
            label=label,
            latency_ms=100.0,
        )

        assert response.content == "Hello, world!"
        assert response.label == label
        assert response.latency_ms == 100.0
        assert response.success is True

    def test_response_with_error(self):
        """Test response with error."""
        label = Label.parse("chat.openai.gpt-4o")
        response = LLMResponse(
            content="",
            label=label,
            latency_ms=100.0,
            error=TimeoutError("Request timed out"),
        )

        assert response.success is False
        assert isinstance(response.error, TimeoutError)


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def test_registry_singleton(self):
        """Test registry is a singleton."""
        ProviderRegistry.reset_instance()
        registry1 = ProviderRegistry.get_instance()
        registry2 = ProviderRegistry.get_instance()

        assert registry1 is registry2
        ProviderRegistry.reset_instance()

    def test_list_providers(self):
        """Test listing providers."""
        ProviderRegistry.reset_instance()
        registry = ProviderRegistry.get_instance()

        providers = registry.list_providers()
        provider_names = [p.name for p in providers]

        assert "openai" in provider_names
        assert "anthropic" in provider_names
        assert "ollama" in provider_names
        ProviderRegistry.reset_instance()

    def test_has_provider(self):
        """Test checking if provider exists."""
        ProviderRegistry.reset_instance()
        registry = ProviderRegistry.get_instance()

        assert registry.has_provider("openai") is True
        assert registry.has_provider("nonexistent") is False
        ProviderRegistry.reset_instance()


class TestProviderInstanceConfig:
    """Tests for ProviderInstanceConfig."""

    def test_config_creation(self):
        """Test creating provider instance config."""
        config = ProviderInstanceConfig(
            name="test_provider",
            provider_type="openai",
            model="gpt-4o",
            api_key="test-key",
            base_url="https://api.openai.com/v1",
        )

        assert config.name == "test_provider"
        assert config.provider_type == "openai"
        assert config.model == "gpt-4o"
        assert config.rpm_limit == 60  # Default
        assert config.concurrency == 5  # Default

    def test_supports_llm_type(self):
        """Test checking LLM type support."""
        from core.llm.registry import ProviderCapability

        config = ProviderInstanceConfig(
            name="test",
            provider_type="openai",
            model="gpt-4o",
            capabilities=frozenset({ProviderCapability.CHAT}),
        )

        assert config.supports(LLMType.CHAT) is True
        assert config.supports(LLMType.EMBEDDING) is False


class TestPoolManagerConfig:
    """Tests for PoolManagerConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PoolManagerConfig()

        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_timeout == 60.0
        assert config.default_timeout == 120.0
        assert config.max_retries == 3

    def test_custom_config(self):
        """Test custom configuration values."""
        config = PoolManagerConfig(
            circuit_breaker_threshold=3,
            circuit_breaker_timeout=30.0,
        )

        assert config.circuit_breaker_threshold == 3
        assert config.circuit_breaker_timeout == 30.0


class TestLabelRouter:
    """Tests for LabelRouter."""

    def test_routing_strategy_enum(self):
        """Test routing strategy enum values."""
        assert RoutingStrategy.PRIORITY.value == "priority"
        assert RoutingStrategy.WEIGHTED.value == "weighted"
        assert RoutingStrategy.LEAST_LATENCY.value == "least_latency"


class TestExceptions:
    """Tests for custom exceptions."""

    def test_invalid_label_error(self):
        """Test InvalidLabelError."""
        error = InvalidLabelError("invalid.label")
        assert error.label == "invalid.label"
        assert "invalid.label" in str(error)

    def test_provider_not_found_error(self):
        """Test ProviderNotFoundError."""
        error = ProviderNotFoundError("nonexistent")
        assert error.provider_type == "nonexistent"
        assert "nonexistent" in str(error)

    def test_all_providers_failed_error(self):
        """Test AllProvidersFailedError."""
        label = Label.parse("chat.openai.gpt-4o")
        error = AllProvidersFailedError(label, ["openai", "anthropic"])
        assert error.label == label
        assert error.providers == ["openai", "anthropic"]
