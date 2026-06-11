# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for ProviderPool failure event publishing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event import EventBus, LLMFailureEvent
from core.llm.resilience.pool import AllProvidersFailedError, ProviderPool
from core.llm.types import Capability, Label, LLMType, ModelConfig, ProviderConfig


@pytest.fixture
def mock_event_bus():
    """Create a mock EventBus that tracks published events."""
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def provider_config():
    """Create a test ProviderConfig."""
    model_cfg = ModelConfig(
        model_id="test-model",
        capabilities=frozenset([Capability.CHAT]),
    )
    return ProviderConfig(
        name="test-provider",
        type="openai",
        api_key="test-key",
        base_url="https://api.test.com",
        models={"test-model": model_cfg},
        rpm_limit=100,
        concurrency=5,
        timeout=30.0,
    )


@pytest.fixture
def chat_label():
    """Create a test chat label."""
    return Label(model="test-model", llm_type=LLMType.CHAT, provider="test-provider")


class TestProviderPoolFailureEvent:
    """Test ProviderPool publishes LLMFailureEvent on failure."""

    @pytest.mark.asyncio
    async def test_pool_publishes_failure_event_on_429(
        self, mock_event_bus, provider_config, chat_label
    ):
        """Test that 429 errors trigger LLMFailureEvent publication."""
        pool = ProviderPool(
            config=provider_config,
            event_bus=mock_event_bus,
        )

        # Mock the caller to raise a 429 error
        with patch.object(pool, "_do_call") as mock_call:
            mock_call.side_effect = Exception("Rate limit exceeded: 429")

            with pytest.raises(AllProvidersFailedError):
                await pool.execute(
                    labels=[chat_label],
                    payload={"messages": [{"role": "user", "content": "test"}]},
                    call_point="classifier",
                    article_id="article-123",
                    task_id="task-456",
                )

        # Verify event was published
        mock_event_bus.publish.assert_called()
        published_event = mock_event_bus.publish.call_args[0][0]

        assert isinstance(published_event, LLMFailureEvent)
        assert published_event.call_point == "classifier"
        assert published_event.provider == "test-provider"
        assert published_event.error_type == "Exception"
        assert "429" in published_event.error_detail
        assert published_event.article_id == "article-123"
        assert published_event.task_id == "task-456"
        assert published_event.attempt >= 1
        assert published_event.fallback_tried is False

    @pytest.mark.asyncio
    async def test_pool_publishes_event_with_fallback(
        self, mock_event_bus, provider_config, chat_label
    ):
        """Test that fallback attempts are tracked in failure events."""
        pool = ProviderPool(
            config=provider_config,
            event_bus=mock_event_bus,
        )

        # Mock the caller to always fail
        with patch.object(pool, "_do_call") as mock_call:
            mock_call.side_effect = Exception("API timeout")

            # Create a fallback label
            fallback_label = Label(
                model="test-model", llm_type=LLMType.CHAT, provider="test-provider"
            )

            with pytest.raises(AllProvidersFailedError):
                await pool.execute(
                    labels=[chat_label, fallback_label],
                    payload={"messages": [{"role": "user", "content": "test"}]},
                    call_point="analyzer",
                )

        # Verify event was published
        mock_event_bus.publish.assert_called()
        published_event = mock_event_bus.publish.call_args[0][0]

        assert isinstance(published_event, LLMFailureEvent)
        assert published_event.call_point == "analyzer"
        # The last attempt should have fallback_tried=True
        assert published_event.fallback_tried is True

    @pytest.mark.asyncio
    async def test_pool_requires_event_bus(self, provider_config):
        """Test that ProviderPool requires event_bus parameter."""
        # Should raise TypeError when event_bus is not provided
        with pytest.raises(TypeError):
            ProviderPool(
                config=provider_config,
                # event_bus is missing - should fail
            )

    @pytest.mark.asyncio
    async def test_pool_failure_event_includes_error_context(
        self, mock_event_bus, provider_config, chat_label
    ):
        """Test that failure events include detailed error context."""
        pool = ProviderPool(
            config=provider_config,
            event_bus=mock_event_bus,
        )

        # Mock with a specific error type
        with patch.object(pool, "_do_call") as mock_call:
            mock_call.side_effect = TimeoutError("Connection timed out after 30s")

            with pytest.raises(AllProvidersFailedError):
                await pool.execute(
                    labels=[chat_label],
                    payload={"messages": [{"role": "user", "content": "test"}]},
                    call_point="summarizer",
                    article_id="article-789",
                )

        # Verify event details
        mock_event_bus.publish.assert_called()
        published_event = mock_event_bus.publish.call_args[0][0]

        assert isinstance(published_event, LLMFailureEvent)
        assert published_event.error_type == "TimeoutError"
        assert "Connection timed out" in published_event.error_detail
        assert published_event.call_point == "summarizer"
        assert published_event.article_id == "article-789"
        assert len(published_event.error_detail) <= 500  # Error detail is truncated
