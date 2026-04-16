# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Tests for core.event.bus module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event.bus import (
    BaseEvent,
    CredibilityComputedEvent,
    EventBus,
    LLMCompareEvent,
    LLMFailureEvent,
    LLMUsageEvent,
    MemoryIngestEvent,
)
from core.llm.types import TokenUsage


class TestBaseEvent:
    """Test BaseEvent dataclass."""

    def test_creates_with_auto_timestamp(self):
        """Test BaseEvent creates with automatic timestamp."""
        event = BaseEvent()
        assert isinstance(event.timestamp, datetime)
        assert event.timestamp.tzinfo == UTC

    def test_creates_with_custom_timestamp(self):
        """Test BaseEvent accepts custom timestamp."""
        custom_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        event = BaseEvent(timestamp=custom_ts)
        assert event.timestamp == custom_ts


class TestCredibilityComputedEvent:
    """Test CredibilityComputedEvent."""

    def test_creates_with_defaults(self):
        """Test default values."""
        event = CredibilityComputedEvent()
        assert event.url == ""
        assert event.score == 0.0
        assert event.cross_count == 0
        assert isinstance(event.timestamp, datetime)

    def test_creates_with_values(self):
        """Test custom values."""
        event = CredibilityComputedEvent(
            url="https://example.com",
            score=0.85,
            cross_count=5,
        )
        assert event.url == "https://example.com"
        assert event.score == 0.85
        assert event.cross_count == 5


class TestLLMFailureEvent:
    """Test LLMFailureEvent."""

    def test_creates_with_defaults(self):
        """Test default values."""
        event = LLMFailureEvent()
        assert event.call_point == ""
        assert event.provider == ""
        assert event.error_type == ""
        assert event.error_detail == ""
        assert event.latency_ms == 0.0
        assert event.article_id is None
        assert event.task_id is None
        assert event.attempt == 0
        assert event.fallback_tried is False

    def test_creates_with_values(self):
        """Test custom values."""
        event = LLMFailureEvent(
            call_point="classifier",
            provider="openai",
            error_type="RateLimitError",
            error_detail="Rate limit exceeded",
            latency_ms=1500.0,
            article_id="123",
            task_id="task-456",
            attempt=3,
            fallback_tried=True,
        )
        assert event.call_point == "classifier"
        assert event.provider == "openai"
        assert event.error_type == "RateLimitError"
        assert event.latency_ms == 1500.0
        assert event.attempt == 3


class TestLLMUsageEvent:
    """Test LLMUsageEvent."""

    def test_creates_with_defaults(self):
        """Test default values."""
        event = LLMUsageEvent()
        assert event.label == ""
        assert event.call_point == ""
        assert event.llm_type == ""
        assert event.provider == ""
        assert event.model == ""
        assert isinstance(event.tokens, TokenUsage)
        assert event.latency_ms == 0.0
        assert event.success is True
        assert event.error_type is None

    def test_creates_with_values(self):
        """Test custom values."""
        tokens = TokenUsage(prompt=100, completion=50, total=150)
        event = LLMUsageEvent(
            label="chat.openai.GPT-4",
            call_point="classifier",
            llm_type="chat",
            provider="openai",
            model="GPT-4",
            tokens=tokens,
            latency_ms=2000.0,
            success=False,
            error_type="TimeoutError",
            article_id=123,
            task_id="task-789",
        )
        assert event.label == "chat.openai.GPT-4"
        assert event.tokens.total == 150
        assert event.success is False


class TestLLMCompareEvent:
    """Test LLMCompareEvent."""

    def test_creates_with_defaults(self):
        """Test default values."""
        event = LLMCompareEvent()
        assert event.call_point == ""
        assert event.primary_model == ""
        assert event.candidate_model == ""
        assert event.primary_latency == 0.0
        assert event.candidate_latency == 0.0
        assert event.primary_success is True
        assert event.candidate_success is True
        assert isinstance(event.primary_tokens, TokenUsage)
        assert isinstance(event.candidate_tokens, TokenUsage)

    def test_creates_with_values(self):
        """Test custom values."""
        event = LLMCompareEvent(
            call_point="entity_extractor",
            primary_model="chat.openai.GPT-4",
            candidate_model="chat.anthropic.Claude",
            primary_latency=2000.0,
            candidate_latency=1500.0,
            primary_success=True,
            candidate_success=True,
        )
        assert event.primary_model == "chat.openai.GPT-4"
        assert event.candidate_model == "chat.anthropic.Claude"


class TestMemoryIngestEvent:
    """Test MemoryIngestEvent."""

    def test_creates_with_defaults(self):
        """Test default values."""
        event = MemoryIngestEvent()
        assert event.article_id == ""
        assert event.state == {}

    def test_creates_with_values(self):
        """Test custom values."""
        state = {"status": "completed", "score": 0.9}
        event = MemoryIngestEvent(article_id="article-123", state=state)
        assert event.article_id == "article-123"
        assert event.state == state


class TestEventBus:
    """Test EventBus."""

    @pytest.fixture
    def bus(self):
        """Create EventBus instance."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, bus):
        """Test basic subscribe and publish flow."""
        called = []

        async def handler(event):
            called.append(event)

        bus.subscribe(BaseEvent, handler)

        event = BaseEvent()
        await bus.publish(event)

        assert called == [event]

    @pytest.mark.asyncio
    async def test_publish_to_multiple_handlers(self, bus):
        """Test publishing to multiple handlers."""
        called1 = []
        called2 = []

        async def handler1(event):
            called1.append(event)

        async def handler2(event):
            called2.append(event)

        bus.subscribe(BaseEvent, handler1)
        bus.subscribe(BaseEvent, handler2)

        event = BaseEvent()
        await bus.publish(event)

        assert called1 == [event]
        assert called2 == [event]

    @pytest.mark.asyncio
    async def test_publish_to_specific_event_type(self, bus):
        """Test handlers only receive their event type."""
        called1 = []
        called2 = []

        async def handler1(event):
            called1.append(event)

        async def handler2(event):
            called2.append(event)

        bus.subscribe(CredibilityComputedEvent, handler1)
        bus.subscribe(LLMFailureEvent, handler2)

        event = CredibilityComputedEvent()
        await bus.publish(event)

        assert called1 == [event]
        assert called2 == []

    @pytest.mark.asyncio
    async def test_publish_with_no_handlers(self, bus):
        """Test publish with no registered handlers."""
        event = BaseEvent()
        await bus.publish(event)  # Should not raise

    @pytest.mark.asyncio
    async def test_handler_error_isolation(self, bus):
        """Test that handler errors don't prevent other handlers."""

        async def failing_handler(event):
            raise ValueError("Handler error")

        called = []

        async def successful_handler(event):
            called.append(event)

        bus.subscribe(BaseEvent, failing_handler)
        bus.subscribe(BaseEvent, successful_handler)

        event = BaseEvent()
        await bus.publish(event)

        # Successful handler should still be called
        assert called == [event]

    @pytest.mark.asyncio
    async def test_multiple_handlers_all_called_on_error(self, bus):
        """Test all handlers are called even if some fail."""
        call_order = []

        async def handler1(event):
            call_order.append("handler1")
            raise ValueError("Error 1")

        async def handler2(event):
            call_order.append("handler2")

        async def handler3(event):
            call_order.append("handler3")
            raise RuntimeError("Error 2")

        bus.subscribe(BaseEvent, handler1)
        bus.subscribe(BaseEvent, handler2)
        bus.subscribe(BaseEvent, handler3)

        event = BaseEvent()
        await bus.publish(event)

        # All handlers should be called
        assert "handler1" in call_order
        assert "handler2" in call_order
        assert "handler3" in call_order

    def test_subscribe_logs_debug(self, bus):
        """Test subscribe logs debug message."""

        async def handler(event):
            pass

        with patch("core.event.bus.log") as mock_log:
            bus.subscribe(BaseEvent, handler)
            mock_log.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_logs_debug(self, bus):
        """Test publish logs debug message."""

        async def handler(event):
            pass

        bus.subscribe(BaseEvent, handler)

        with patch("core.event.bus.log") as mock_log:
            event = BaseEvent()
            await bus.publish(event)
            mock_log.debug.assert_called()

    @pytest.mark.asyncio
    async def test_handler_error_logs_error(self, bus):
        """Test handler errors are logged."""

        async def failing_handler(event):
            raise ValueError("Test error")

        bus.subscribe(BaseEvent, failing_handler)

        with patch("core.event.bus.log") as mock_log:
            event = BaseEvent()
            await bus.publish(event)
            mock_log.error.assert_called_once()

    def test_get_signal_creates_once(self, bus):
        """Test _get_signal creates signal only once."""
        signal1 = bus._get_signal(BaseEvent)
        signal2 = bus._get_signal(BaseEvent)
        assert signal1 is signal2

    def test_subscribe_multiple_event_types(self, bus):
        """Test subscribing to multiple event types."""

        async def handler(event):
            pass

        bus.subscribe(CredibilityComputedEvent, handler)
        bus.subscribe(LLMFailureEvent, handler)

        assert len(bus._handlers[CredibilityComputedEvent]) == 1
        assert len(bus._handlers[LLMFailureEvent]) == 1
