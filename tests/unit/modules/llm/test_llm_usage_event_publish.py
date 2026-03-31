# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMUsageEvent publishing in pool_manager and queue_manager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event.bus import EventBus, LLMFailureEvent, LLMUsageEvent
from core.llm.label import Label
from core.llm.pool_manager import PoolManagerConfig, ProviderPoolManager
from core.llm.queue_manager import LLMQueueManager, ProviderQueue
from core.llm.request import LLMCallResult, LLMRequest, TokenUsage
from core.llm.types import LLMType


class TestPoolManagerUsageEvent:
    """Tests for LLMUsageEvent publishing in ProviderPoolManager."""

    @pytest.mark.asyncio
    async def test_execute_publishes_usage_event_on_success(self):
        """Test that execute() publishes LLMUsageEvent on successful call."""
        event_bus = EventBus()
        published_events: list[LLMUsageEvent] = []

        async def capture_event(event: LLMUsageEvent) -> None:
            published_events.append(event)

        event_bus.subscribe(LLMUsageEvent, capture_event)

        # Mock registry and pool
        mock_registry = MagicMock()
        mock_pool = MagicMock()
        mock_pool.name = "test_provider"
        mock_pool.config.model = "test-model"
        mock_pool.config.supports.return_value = True
        mock_pool.health_status.value = "healthy"
        mock_pool.submit = AsyncMock(
            return_value=MagicMock(
                token_usage=TokenUsage(input_tokens=100, output_tokens=50),
                latency_ms=150.0,
            )
        )

        manager = ProviderPoolManager(
            registry=mock_registry,
            event_bus=event_bus,
        )
        manager._pools = {"test_provider": mock_pool}

        label = Label(llm_type=LLMType.CHAT, provider="test_provider", model="test-model")
        request = LLMRequest(
            label=label,
            payload={"prompt": "test"},
            metadata={"call_point": "test_pipeline", "article_id": 123},
        )

        await manager.execute(request)

        assert len(published_events) == 1
        event = published_events[0]
        assert event.success is True
        assert event.provider == "test_provider"
        assert event.model == "test-model"
        assert event.llm_type == "chat"
        assert event.call_point == "test_pipeline"
        assert event.article_id == 123
        assert event.tokens.input_tokens == 100
        assert event.tokens.output_tokens == 50
        assert event.latency_ms == 150.0

    @pytest.mark.asyncio
    async def test_execute_publishes_failure_event_on_provider_exception(self):
        """Test that execute() publishes LLMFailureEvent when provider throws exception."""
        event_bus = EventBus()
        published_events: list[LLMFailureEvent] = []

        async def capture_event(event: LLMFailureEvent) -> None:
            published_events.append(event)

        event_bus.subscribe(LLMFailureEvent, capture_event)

        # Mock registry with provider that throws exception
        mock_registry = MagicMock()
        mock_pool = MagicMock()
        mock_pool.name = "test_provider"
        mock_pool.config.model = "test-model"
        mock_pool.config.supports.return_value = True
        mock_pool.health_status.value = "healthy"
        mock_pool.submit = AsyncMock(side_effect=TimeoutError("Connection timeout"))

        manager = ProviderPoolManager(
            registry=mock_registry,
            event_bus=event_bus,
        )
        manager._pools = {"test_provider": mock_pool}

        label = Label(llm_type=LLMType.CHAT, provider="test_provider", model="test-model")
        request = LLMRequest(
            label=label,
            payload={"prompt": "test"},
            metadata={"call_point": "test_pipeline", "article_id": 456, "task_id": "task-789"},
        )

        with pytest.raises(Exception):  # AllProvidersFailedError
            await manager.execute(request)

        assert len(published_events) == 1
        event = published_events[0]
        assert event.call_point == "chat"
        assert event.provider == "test_provider"
        assert event.error_type == "TimeoutError"
        assert event.article_id == 456
        assert event.task_id == "task-789"

    @pytest.mark.asyncio
    async def test_execute_handles_event_publish_exception(self):
        """Test that event publish exceptions are caught and logged."""
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(side_effect=RuntimeError("Event bus error"))

        mock_pool = MagicMock()
        mock_pool.name = "test_provider"
        mock_pool.config.model = "test-model"
        mock_pool.config.supports.return_value = True
        mock_pool.health_status.value = "healthy"
        mock_pool.submit = AsyncMock(
            return_value=MagicMock(
                token_usage=TokenUsage(input_tokens=100, output_tokens=50),
                latency_ms=150.0,
            )
        )

        manager = ProviderPoolManager(
            registry=MagicMock(),
            event_bus=event_bus,
        )
        manager._pools = {"test_provider": mock_pool}

        label = Label(llm_type=LLMType.CHAT, provider="test_provider", model="test-model")
        request = LLMRequest(
            label=label,
            payload={"prompt": "test"},
        )

        # Should not raise, event publish error is caught
        response = await manager.execute(request)
        assert response is not None


class TestProviderQueueUsageEvent:
    """Tests for LLMUsageEvent publishing in ProviderQueue._dispatch."""

    @pytest.mark.asyncio
    async def test_dispatch_publishes_usage_event_on_success(self):
        """Test that _dispatch publishes LLMUsageEvent on successful call."""
        event_bus = EventBus()
        published_events: list[LLMUsageEvent] = []

        async def capture_event(event: LLMUsageEvent) -> None:
            published_events.append(event)

        event_bus.subscribe(LLMUsageEvent, capture_event)

        # Mock provider
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(
            return_value=LLMCallResult(
                content="Hello, world!",
                token_usage=TokenUsage(input_tokens=50, output_tokens=20),
            )
        )

        queue = ProviderQueue(
            provider_name="test_provider",
            concurrency=1,
            provider=mock_provider,
            model="gpt-4",
            event_bus=event_bus,
        )

        task = MagicMock()
        task.call_point = MagicMock()
        task.call_point.value = "entity_extractor"
        task.payload = {
            "system_prompt": "You are helpful.",
            "user_content": "Hello",
            "article_id": 789,
            "task_id": "task-001",
        }

        result = await queue._dispatch(task)

        assert result == "Hello, world!"
        assert len(published_events) == 1
        event = published_events[0]
        assert event.success is True
        assert event.provider == "test_provider"
        assert event.model == "gpt-4"
        assert event.llm_type == "chat"
        assert event.call_point == "entity_extractor"
        assert event.article_id == 789
        assert event.task_id == "task-001"
        assert event.tokens.input_tokens == 50
        assert event.tokens.output_tokens == 20
        assert event.latency_ms > 0

    @pytest.mark.asyncio
    async def test_dispatch_publishes_usage_event_on_failure(self):
        """Test that _dispatch publishes LLMUsageEvent on failure."""
        event_bus = EventBus()
        published_events: list[LLMUsageEvent] = []

        async def capture_event(event: LLMUsageEvent) -> None:
            published_events.append(event)

        event_bus.subscribe(LLMUsageEvent, capture_event)

        # Mock provider that raises
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(side_effect=TimeoutError("Connection timeout"))

        queue = ProviderQueue(
            provider_name="test_provider",
            concurrency=1,
            provider=mock_provider,
            model="gpt-4",
            event_bus=event_bus,
        )

        task = MagicMock()
        task.call_point = MagicMock()
        task.call_point.value = "summarizer"
        task.payload = {
            "system_prompt": "You are helpful.",
            "user_content": "Test",
            "article_id": 999,
        }

        with pytest.raises(TimeoutError):
            await queue._dispatch(task)

        assert len(published_events) == 1
        event = published_events[0]
        assert event.success is False
        assert event.error_type == "TimeoutError"
        assert event.provider == "test_provider"
        assert event.model == "gpt-4"
        assert event.call_point == "summarizer"
        assert event.article_id == 999
        assert event.latency_ms > 0

    @pytest.mark.asyncio
    async def test_dispatch_without_event_bus_succeeds(self):
        """Test that _dispatch works without event_bus (event_bus=None)."""
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(
            return_value=LLMCallResult(
                content="Response",
                token_usage=TokenUsage(input_tokens=10, output_tokens=5),
            )
        )

        queue = ProviderQueue(
            provider_name="test_provider",
            concurrency=1,
            provider=mock_provider,
            model="gpt-4",
            event_bus=None,  # No event bus
        )

        task = MagicMock()
        task.call_point = MagicMock()
        task.call_point.value = "test_call"
        task.payload = {"system_prompt": "", "user_content": "test"}

        result = await queue._dispatch(task)

        assert result == "Response"

    @pytest.mark.asyncio
    async def test_dispatch_handles_event_publish_exception(self):
        """Test that event publish exceptions in _dispatch are caught."""
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(side_effect=RuntimeError("Event bus error"))

        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(
            return_value=LLMCallResult(
                content="Response",
                token_usage=TokenUsage(input_tokens=10, output_tokens=5),
            )
        )

        queue = ProviderQueue(
            provider_name="test_provider",
            concurrency=1,
            provider=mock_provider,
            model="gpt-4",
            event_bus=event_bus,
        )

        task = MagicMock()
        task.call_point = MagicMock()
        task.call_point.value = "test_call"
        task.payload = {"system_prompt": "", "user_content": "test"}

        # Should not raise, event publish error is caught
        result = await queue._dispatch(task)
        assert result == "Response"


class TestEventBusIntegration:
    """Integration tests for EventBus with LLMUsageEvent."""

    def test_event_bus_subscribes_to_llm_usage_event(self):
        """Test EventBus can subscribe to LLMUsageEvent."""
        event_bus = EventBus()
        handler_called = []

        async def handler(event: LLMUsageEvent) -> None:
            handler_called.append(event)

        event_bus.subscribe(LLMUsageEvent, handler)

        # Verify subscription
        assert LLMUsageEvent in event_bus._handlers
        assert len(event_bus._handlers[LLMUsageEvent]) == 1

    @pytest.mark.asyncio
    async def test_event_bus_publishes_to_multiple_handlers(self):
        """Test EventBus publishes LLMUsageEvent to all subscribed handlers."""
        event_bus = EventBus()
        events_captured: list[LLMUsageEvent] = []

        async def handler1(event: LLMUsageEvent) -> None:
            events_captured.append(event)

        async def handler2(event: LLMUsageEvent) -> None:
            events_captured.append(event)

        event_bus.subscribe(LLMUsageEvent, handler1)
        event_bus.subscribe(LLMUsageEvent, handler2)

        test_event = LLMUsageEvent(
            label="chat::test::gpt-4",
            call_point="test",
            llm_type="chat",
            provider="test",
            model="gpt-4",
            tokens=TokenUsage(input_tokens=10, output_tokens=5),
            latency_ms=100.0,
            success=True,
        )

        await event_bus.publish(test_event)

        assert len(events_captured) == 2
        assert all(e == test_event for e in events_captured)

    @pytest.mark.asyncio
    async def test_event_bus_handler_exception_isolation(self):
        """Test that one handler exception doesn't affect others."""
        event_bus = EventBus()
        successful_handler_called = []

        async def failing_handler(event: LLMUsageEvent) -> None:
            raise RuntimeError("Handler error")

        async def successful_handler(event: LLMUsageEvent) -> None:
            successful_handler_called.append(event)

        event_bus.subscribe(LLMUsageEvent, failing_handler)
        event_bus.subscribe(LLMUsageEvent, successful_handler)

        test_event = LLMUsageEvent(
            label="chat::test::gpt-4",
            call_point="test",
            llm_type="chat",
            provider="test",
            model="gpt-4",
            tokens=TokenUsage(),
            latency_ms=100.0,
            success=True,
        )

        # Should not raise, failing handler is isolated
        await event_bus.publish(test_event)

        assert len(successful_handler_called) == 1


class TestTokenUsage:
    """Tests for TokenUsage dataclass."""

    def test_token_usage_defaults(self):
        """Test TokenUsage default values."""
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_tokens == 0

    def test_token_usage_auto_calculates_total(self):
        """Test TokenUsage auto-calculates total_tokens."""
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150

    def test_token_usage_respects_explicit_total(self):
        """Test TokenUsage respects explicit total_tokens."""
        usage = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=200)
        assert usage.total_tokens == 200
