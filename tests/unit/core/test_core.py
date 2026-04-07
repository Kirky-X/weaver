# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for core modules."""

from unittest.mock import MagicMock

import pytest


class TestPipelineState:
    """Tests for PipelineState."""

    def test_state_initialization(self):
        """Test PipelineState can be initialized."""
        from modules.processing.pipeline.state import PipelineState

        state = PipelineState()
        assert state is not None
        assert isinstance(state, dict)

    def test_state_set_item(self):
        """Test PipelineState can set items."""
        from modules.processing.pipeline.state import PipelineState

        state = PipelineState()
        state["test_key"] = "test_value"
        assert state["test_key"] == "test_value"


class TestSourceModels:
    """Tests for source models."""

    def test_source_config_creation(self):
        """Test SourceConfig can be created."""
        from modules.ingestion.domain.models import SourceConfig

        config = SourceConfig(
            id="test_source",
            name="Test Source",
            url="https://example.com/feed.xml",
        )
        assert config.id == "test_source"
        assert config.name == "Test Source"
        assert config.url == "https://example.com/feed.xml"
        assert config.enabled is True
        assert config.source_type == "rss"

    def test_news_item_creation(self):
        """Test NewsItem can be created."""
        from modules.ingestion.domain.models import NewsItem

        item = NewsItem(
            url="https://example.com/article1",
            title="Test Article",
            source="test_source",
            source_host="example.com",
        )
        assert item.url == "https://example.com/article1"
        assert item.title == "Test Article"


class TestCollectorModels:
    """Tests for collector models."""

    def test_article_raw_creation(self):
        """Test ArticleRaw can be created."""
        from modules.ingestion.domain.models import ArticleRaw

        raw = ArticleRaw(
            url="https://example.com/article",
            title="Test Title",
            body="Test body content",
            source="test",
            source_host="example.com",
        )
        assert raw.url == "https://example.com/article"
        assert raw.title == "Test Title"
        assert raw.body == "Test body content"


class TestEventBus:
    """Tests for EventBus."""

    @pytest.mark.asyncio
    async def test_event_bus_publish_subscribe(self):
        """Test event bus publish and subscribe."""
        from core.event.bus import BaseEvent, EventBus

        bus = EventBus()
        received_events = []

        async def handler(event: BaseEvent):
            received_events.append(event)

        bus.subscribe(BaseEvent, handler)

        event = BaseEvent()
        await bus.publish(event)

        assert len(received_events) == 1
        assert received_events[0] is event

    @pytest.mark.asyncio
    async def test_event_bus_no_handlers(self):
        """Test event bus handles no handlers gracefully."""
        from core.event.bus import BaseEvent, EventBus

        bus = EventBus()
        event = BaseEvent()

        # Should not raise
        await bus.publish(event)


class TestLLMTypes:
    """Tests for LLM types."""

    def test_llm_task_creation(self):
        """Test LLMTask can be created."""
        from core.llm.types import CallPoint, LLMTask, LLMType

        task = LLMTask(
            call_point=CallPoint.CLASSIFIER,
            llm_type=LLMType.CHAT,
            payload={"prompt": "Test prompt"},
        )
        assert task.call_point == CallPoint.CLASSIFIER
        assert task.llm_type == LLMType.CHAT

    def test_call_point_enum(self):
        """Test CallPoint enum values."""
        from core.llm.types import CallPoint

        assert CallPoint.CLASSIFIER.value == "classifier"
        assert CallPoint.CLEANER.value == "cleaner"
        assert CallPoint.CATEGORIZER.value == "categorizer"


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_circuit_breaker_initial_state(self):
        """Test circuit breaker starts in closed state."""
        from core.resilience.circuit_breaker import CBState, CircuitBreaker

        cb = CircuitBreaker(
            threshold=3,
            timeout_secs=60.0,
        )
        assert cb.state == CBState.CLOSED

    async def test_circuit_breaker_record_success(self):
        """Test circuit breaker records success."""
        from core.resilience.circuit_breaker import CBState, CircuitBreaker

        cb = CircuitBreaker(
            threshold=3,
            timeout_secs=60.0,
        )
        await cb.record_success()
        assert cb.state == CBState.CLOSED

    async def test_circuit_breaker_record_failure(self):
        """Test circuit breaker records failure."""
        from core.resilience.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            threshold=3,
            timeout_secs=60.0,
        )
        await cb.record_failure()
        await cb.record_failure()
        assert cb._fail_count == 2


class TestPromptLoader:
    """Tests for PromptLoader."""

    def test_prompt_loader_initialization(self):
        """Test prompt loader initializes."""
        from pathlib import Path

        from core.prompt.loader import PromptLoader

        loader = PromptLoader("config/prompts")
        assert loader._path == Path("config/prompts")


class TestTokenBudget:
    """Tests for TokenBudgetManager."""

    def test_token_budget_manager_initialization(self):
        """Test TokenBudgetManager can be created."""
        from core.llm.token_budget import DEFAULT_LIMIT, TokenBudgetManager

        manager = TokenBudgetManager()
        assert manager is not None
        assert DEFAULT_LIMIT == 4000
