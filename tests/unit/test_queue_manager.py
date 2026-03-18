# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for LLMQueueManager module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm.queue_manager import (
    FALLBACK_ERRORS,
    NON_RETRYABLE_STATUS,
    SELF_RETRY_ERRORS,
    LLMQueueManager,
    ProviderQueue,
)
from core.llm.types import CallPoint, LLMTask, LLMType


class TestProviderQueue:
    """Tests for ProviderQueue."""

    def test_initialization(self):
        """Test queue initializes correctly."""
        mock_provider = MagicMock()
        queue = ProviderQueue("openai", concurrency=5, provider=mock_provider)
        assert queue.name == "openai"
        assert queue.circuit_breaker is not None

    @pytest.mark.asyncio
    async def test_enqueue(self):
        """Test enqueueing a task."""
        mock_provider = MagicMock()
        queue = ProviderQueue("openai", concurrency=1, provider=mock_provider)
        task = LLMTask(
            call_point=CallPoint.CLASSIFIER, llm_type=LLMType.CHAT, payload={"prompt": "test"}
        )

        future = await queue.enqueue(task)

        assert future is not None
        assert task.future is future

    def test_circuit_breaker_attached(self):
        """Test circuit breaker is attached to queue."""
        mock_provider = MagicMock()
        queue = ProviderQueue("openai", concurrency=1, provider=mock_provider)
        assert hasattr(queue, "circuit_breaker")


class TestLLMQueueManager:
    """Tests for LLMQueueManager."""

    @pytest.fixture
    def mock_config_manager(self):
        """Mock config manager."""
        manager = MagicMock()
        manager.list_providers = MagicMock(return_value=[])
        manager.get_call_point_config = MagicMock(
            return_value=MagicMock(primary=MagicMock(provider="openai", rpm_limit=60), fallbacks=[])
        )
        manager.get_embedding_config = MagicMock(return_value=None)
        return manager

    @pytest.fixture
    def mock_rate_limiter(self):
        """Mock rate limiter."""
        limiter = MagicMock()
        limiter.consume = AsyncMock(return_value=0.0)
        return limiter

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    def test_initialization(self, mock_config_manager, mock_rate_limiter, mock_event_bus):
        """Test queue manager initializes correctly."""
        manager = LLMQueueManager(
            config_manager=mock_config_manager,
            rate_limiter=mock_rate_limiter,
            event_bus=mock_event_bus,
        )
        assert manager._config is mock_config_manager
        assert manager._rate_limiter is mock_rate_limiter

    @pytest.mark.asyncio
    async def test_startup_no_providers(
        self, mock_config_manager, mock_rate_limiter, mock_event_bus
    ):
        """Test startup with no providers."""
        manager = LLMQueueManager(
            config_manager=mock_config_manager,
            rate_limiter=mock_rate_limiter,
            event_bus=mock_event_bus,
        )

        await manager.startup()

        mock_config_manager.list_providers.assert_called_once()


class TestFallbackErrors:
    """Tests for fallback error handling."""

    def test_fallback_errors_defined(self):
        """Test fallback errors are defined."""
        assert TimeoutError in FALLBACK_ERRORS
        assert ConnectionError in FALLBACK_ERRORS

    def test_self_retry_errors_defined(self):
        """Test self retry errors are defined."""
        assert "OutputParserException" in SELF_RETRY_ERRORS

    def test_non_retryable_status_defined(self):
        """Test non retryable status codes are defined."""
        assert 400 in NON_RETRYABLE_STATUS
        assert 401 in NON_RETRYABLE_STATUS
        assert 403 in NON_RETRYABLE_STATUS
        assert 413 in NON_RETRYABLE_STATUS


class TestLLMTask:
    """Tests for LLMTask."""

    def test_task_creation(self):
        """Test task creation."""
        task = LLMTask(
            call_point=CallPoint.CLASSIFIER, llm_type=LLMType.CHAT, payload={"prompt": "test"}
        )
        assert task.call_point == CallPoint.CLASSIFIER
        assert task.llm_type == LLMType.CHAT
        assert task.priority == 5
        assert task.attempt == 0

    def test_task_priority(self):
        """Test task priority."""
        task = LLMTask(
            call_point=CallPoint.CLASSIFIER, llm_type=LLMType.CHAT, payload={}, priority=1
        )
        assert task.priority == 1

    def test_task_attempt_count(self):
        """Test task attempt count."""
        task = LLMTask(
            call_point=CallPoint.CLASSIFIER, llm_type=LLMType.CHAT, payload={}, attempt=2
        )
        assert task.attempt == 2
