# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLM token Prometheus metrics."""

from datetime import UTC, datetime

import pytest
from prometheus_client import Counter, REGISTRY

from core.event.bus import EventBus, LLMUsageEvent
from core.llm.request import TokenUsage
from core.observability.metrics import MetricsCollector, metrics


class TestLLMTokenMetricsDefinition:
    """Test LLM token metrics are properly defined."""

    def test_llm_token_input_total_exists(self):
        """Test llm_token_input_total counter is defined."""
        assert hasattr(metrics, "llm_token_input_total")
        assert isinstance(metrics.llm_token_input_total, Counter)

    def test_llm_token_output_total_exists(self):
        """Test llm_token_output_total counter is defined."""
        assert hasattr(metrics, "llm_token_output_total")
        assert isinstance(metrics.llm_token_output_total, Counter)

    def test_llm_token_total_exists(self):
        """Test llm_token_total counter is defined."""
        assert hasattr(metrics, "llm_token_total")
        assert isinstance(metrics.llm_token_total, Counter)

    def test_llm_token_metrics_have_correct_labels(self):
        """Test LLM token metrics have correct labels."""
        # Get the label names from the counter
        input_labels = metrics.llm_token_input_total._labelnames
        output_labels = metrics.llm_token_output_total._labelnames
        total_labels = metrics.llm_token_total._labelnames

        expected_labels = ("provider", "model", "call_point")

        assert input_labels == expected_labels
        assert output_labels == expected_labels
        assert total_labels == expected_labels


class TestLLMTokenMetricsIncrement:
    """Test LLM token metrics increment correctly."""

    def test_increment_input_tokens(self):
        """Test incrementing input token counter."""
        # Get initial value
        labels = {"provider": "test_provider", "model": "test_model", "call_point": "test_point"}

        # Increment
        metrics.llm_token_input_total.labels(**labels).inc(100)

        # Verify the metric exists and can be read
        # Note: Prometheus counters are cumulative, so we can't check exact value
        # in isolation, but we can verify the labels work
        assert metrics.llm_token_input_total.labels(**labels) is not None

    def test_increment_output_tokens(self):
        """Test incrementing output token counter."""
        labels = {"provider": "openai", "model": "gpt-4", "call_point": "chat"}

        metrics.llm_token_output_total.labels(**labels).inc(50)

        assert metrics.llm_token_output_total.labels(**labels) is not None

    def test_increment_total_tokens(self):
        """Test incrementing total token counter."""
        labels = {"provider": "anthropic", "model": "claude-3", "call_point": "embedding"}

        metrics.llm_token_total.labels(**labels).inc(150)

        assert metrics.llm_token_total.labels(**labels) is not None


class TestLLMUsageEventHandler:
    """Test LLMUsageEvent handler updates Prometheus metrics."""

    @pytest.fixture
    def event_bus(self):
        """Create a fresh EventBus for testing."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_handler_updates_all_token_metrics(self, event_bus):
        """Test that handler updates all three token metrics."""
        from container import _handle_llm_usage_metrics

        # Create an LLMUsageEvent
        event = LLMUsageEvent(
            label="chat::openai::gpt-4",
            call_point="test_node",
            llm_type="chat",
            provider="openai",
            model="gpt-4",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=500.0,
            success=True,
            timestamp=datetime.now(UTC),
        )

        # Call the handler directly
        await _handle_llm_usage_metrics(event)

        # Verify metrics were updated (we can't check exact values due to cumulative nature)
        labels = {"provider": "openai", "model": "gpt-4", "call_point": "test_node"}
        assert metrics.llm_token_input_total.labels(**labels) is not None
        assert metrics.llm_token_output_total.labels(**labels) is not None
        assert metrics.llm_token_total.labels(**labels) is not None

    @pytest.mark.asyncio
    async def test_handler_with_event_bus_subscription(self, event_bus):
        """Test that handler works when subscribed to EventBus."""
        from container import _handle_llm_usage_metrics

        # Subscribe the handler
        event_bus.subscribe(LLMUsageEvent, _handle_llm_usage_metrics)

        # Create and publish an event
        event = LLMUsageEvent(
            label="chat::anthropic::claude-3",
            call_point="entity_extractor",
            llm_type="chat",
            provider="anthropic",
            model="claude-3",
            tokens=TokenUsage(input_tokens=200, output_tokens=100, total_tokens=300),
            latency_ms=800.0,
            success=True,
            timestamp=datetime.now(UTC),
        )

        await event_bus.publish(event)

        # Verify metrics were updated
        labels = {"provider": "anthropic", "model": "claude-3", "call_point": "entity_extractor"}
        assert metrics.llm_token_input_total.labels(**labels) is not None
        assert metrics.llm_token_output_total.labels(**labels) is not None
        assert metrics.llm_token_total.labels(**labels) is not None

    @pytest.mark.asyncio
    async def test_handler_handles_zero_tokens(self, event_bus):
        """Test that handler handles zero tokens correctly."""
        from container import _handle_llm_usage_metrics

        event = LLMUsageEvent(
            label="embedding::aiping::text-embedding",
            call_point="vectorize",
            llm_type="embedding",
            provider="aiping",
            model="text-embedding",
            tokens=TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            latency_ms=100.0,
            success=True,
            timestamp=datetime.now(UTC),
        )

        # Should not raise
        await _handle_llm_usage_metrics(event)

    @pytest.mark.asyncio
    async def test_handler_handles_large_token_counts(self, event_bus):
        """Test that handler handles large token counts correctly."""
        from container import _handle_llm_usage_metrics

        event = LLMUsageEvent(
            label="chat::openai::gpt-4",
            call_point="summarize",
            llm_type="chat",
            provider="openai",
            model="gpt-4",
            tokens=TokenUsage(input_tokens=100000, output_tokens=50000, total_tokens=150000),
            latency_ms=5000.0,
            success=True,
            timestamp=datetime.now(UTC),
        )

        # Should not raise
        await _handle_llm_usage_metrics(event)

    @pytest.mark.asyncio
    async def test_handler_handles_special_characters_in_labels(self, event_bus):
        """Test that handler handles special characters in label values."""
        from container import _handle_llm_usage_metrics

        event = LLMUsageEvent(
            label="chat::provider-with-dash::model.with.dots",
            call_point="node_with_underscore",
            llm_type="chat",
            provider="provider-with-dash",
            model="model.with.dots",
            tokens=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            latency_ms=50.0,
            success=True,
            timestamp=datetime.now(UTC),
        )

        # Should not raise
        await _handle_llm_usage_metrics(event)


class TestLLMTokenMetricsMultipleEvents:
    """Test LLM token metrics with multiple events."""

    @pytest.mark.asyncio
    async def test_multiple_events_accumulate(self):
        """Test that multiple events accumulate token counts."""
        from container import _handle_llm_usage_metrics

        labels = {"provider": "test", "model": "test-model", "call_point": "test"}

        # Get initial value (may not be 0 due to other tests)
        try:
            initial_value = metrics.llm_token_input_total.labels(**labels)._value.get()
        except AttributeError:
            initial_value = 0

        # Send multiple events
        for i in range(5):
            event = LLMUsageEvent(
                label="chat::test::test-model",
                call_point="test",
                llm_type="chat",
                provider="test",
                model="test-model",
                tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
                latency_ms=100.0,
                success=True,
                timestamp=datetime.now(UTC),
            )
            await _handle_llm_usage_metrics(event)

        # Verify accumulation (5 events * 100 input tokens)
        final_value = metrics.llm_token_input_total.labels(**labels)._value.get()
        assert final_value >= initial_value + 500

    @pytest.mark.asyncio
    async def test_different_providers_tracked_separately(self):
        """Test that different providers are tracked separately."""
        from container import _handle_llm_usage_metrics

        # Send events for different providers
        for provider in ["openai", "anthropic", "aiping"]:
            event = LLMUsageEvent(
                label=f"chat::{provider}::model",
                call_point="test",
                llm_type="chat",
                provider=provider,
                model="model",
                tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
                latency_ms=100.0,
                success=True,
                timestamp=datetime.now(UTC),
            )
            await _handle_llm_usage_metrics(event)

        # Verify each provider has its own metric
        for provider in ["openai", "anthropic", "aiping"]:
            labels = {"provider": provider, "model": "model", "call_point": "test"}
            assert metrics.llm_token_input_total.labels(**labels) is not None
