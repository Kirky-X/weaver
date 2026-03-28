# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for PoolManager LLMFailureEvent publishing."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core.event.bus import EventBus, LLMFailureEvent
from core.llm.label import Label
from core.llm.pool_manager import (
    AllProvidersFailedError,
    PoolManagerConfig,
    ProviderPoolManager,
)
from core.llm.provider_pool import CircuitOpenError
from core.llm.registry import ProviderRegistry
from core.llm.types import LLMType


class TestPoolManagerLLMFailureEvent:
    """Tests for PoolManager LLMFailureEvent publishing."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock ProviderRegistry."""
        return MagicMock(spec=ProviderRegistry)

    @pytest.fixture
    def mock_rate_limiter(self):
        """Create a mock RedisTokenBucket."""
        return MagicMock()

    @pytest.fixture
    def config(self):
        """Create PoolManagerConfig."""
        return PoolManagerConfig()

    @pytest.fixture
    def event_bus(self):
        """Create an EventBus instance."""
        return EventBus()

    @pytest.fixture
    def pool_manager(self, mock_registry, mock_rate_limiter, config, event_bus):
        """Create ProviderPoolManager with EventBus."""
        return ProviderPoolManager(
            registry=mock_registry,
            rate_limiter=mock_rate_limiter,
            config=config,
            event_bus=event_bus,
        )

    @pytest.fixture
    def mock_pool(self):
        """Create a mock ProviderPool."""
        pool = MagicMock()
        pool.name = "test-provider"
        pool.health_status.value = "healthy"
        pool.config.supports = MagicMock(return_value=True)
        return pool

    def _make_request(self, article_id=None, task_id=None):
        """Create a mock LLMRequest."""
        label = Label(provider="test-provider", llm_type=LLMType.CHAT, model="test-model")
        request = MagicMock()
        request.label = label
        request.payload = {}
        request.priority = 1
        request.timeout = 30.0
        metadata = {}
        if article_id:
            metadata["article_id"] = article_id
        if task_id:
            metadata["task_id"] = task_id
        request.metadata = metadata if metadata else None
        return request

    @pytest.mark.asyncio
    async def test_publishes_llm_failure_event_when_all_providers_fail(
        self, pool_manager, mock_pool
    ):
        """Test PoolManager.execute() publishes LLMFailureEvent when all providers fail."""
        article_id = str(uuid4())
        task_id = "task-123"
        request = self._make_request(article_id=article_id, task_id=task_id)

        # Make pool.submit raise an exception
        mock_pool.submit = AsyncMock(side_effect=Exception("Provider error"))

        # Assign pool to manager
        pool_manager._pools["test-provider"] = mock_pool

        # Track published events
        published_events = []

        async def capture_handler(event):
            published_events.append(event)

        pool_manager._event_bus.subscribe(LLMFailureEvent, capture_handler)

        # Execute should raise AllProvidersFailedError
        with pytest.raises(AllProvidersFailedError):
            await pool_manager.execute(request)

        # Verify event was published
        assert len(published_events) == 1
        event = published_events[0]
        assert event.call_point == "chat"
        assert event.provider == "test-provider"
        assert event.error_type == "Exception"
        assert event.error_detail == "Provider error"
        assert event.article_id == article_id
        assert event.task_id == task_id
        assert event.attempt == 1
        assert event.fallback_tried is False

    @pytest.mark.asyncio
    async def test_no_event_when_event_bus_is_none(self, mock_registry, mock_rate_limiter, config):
        """Test PoolManager.execute() does not fail when event_bus is None."""
        pool_manager = ProviderPoolManager(
            registry=mock_registry,
            rate_limiter=mock_rate_limiter,
            config=config,
            event_bus=None,  # No event bus
        )

        mock_pool = MagicMock()
        mock_pool.name = "test-provider"
        mock_pool.health_status.value = "healthy"
        mock_pool.config.supports = MagicMock(return_value=True)
        mock_pool.submit = AsyncMock(side_effect=Exception("Provider error"))
        pool_manager._pools["test-provider"] = mock_pool

        request = self._make_request()

        # Should raise without error (no event bus to fail)
        with pytest.raises(AllProvidersFailedError):
            await pool_manager.execute(request)

    @pytest.mark.asyncio
    async def test_event_publish_failure_does_not_suppress_original_error(
        self, pool_manager, mock_pool
    ):
        """Test that event publish failure does not suppress AllProvidersFailedError."""
        request = self._make_request()
        mock_pool.submit = AsyncMock(side_effect=Exception("Provider error"))
        pool_manager._pools["test-provider"] = mock_pool

        # Make publish raise an exception
        original_publish = pool_manager._event_bus.publish

        async def failing_publish(event):
            raise RuntimeError("Event bus unavailable")

        pool_manager._event_bus.publish = failing_publish

        # Should still raise AllProvidersFailedError
        with pytest.raises(AllProvidersFailedError) as exc_info:
            await pool_manager.execute(request)

        # Verify the original error is preserved
        assert "All providers failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fallback_tried_flag_set_correctly(self, pool_manager):
        """Test fallback_tried is True when fallback labels are provided."""
        mock_pool1 = MagicMock()
        mock_pool1.name = "primary-provider"
        mock_pool1.health_status.value = "healthy"
        mock_pool1.config.supports = MagicMock(return_value=True)
        mock_pool1.submit = AsyncMock(side_effect=Exception("Primary failed"))

        mock_pool2 = MagicMock()
        mock_pool2.name = "fallback-provider"
        mock_pool2.health_status.value = "healthy"
        mock_pool2.config.supports = MagicMock(return_value=True)
        mock_pool2.submit = AsyncMock(side_effect=Exception("Fallback also failed"))

        pool_manager._pools["primary-provider"] = mock_pool1
        pool_manager._pools["fallback-provider"] = mock_pool2

        label = Label(provider="primary-provider", llm_type=LLMType.CHAT, model="primary-model")
        fallback_label = Label(
            provider="fallback-provider", llm_type=LLMType.CHAT, model="fallback-model"
        )
        request = MagicMock()
        request.label = label
        request.payload = {}
        request.priority = 1
        request.timeout = 30.0
        request.metadata = {}

        published_events = []

        async def capture_handler(event):
            published_events.append(event)

        pool_manager._event_bus.subscribe(LLMFailureEvent, capture_handler)

        with pytest.raises(AllProvidersFailedError):
            await pool_manager.execute(request, fallback_labels=[fallback_label])

        assert len(published_events) == 1
        assert published_events[0].fallback_tried is True
        assert published_events[0].attempt == 2

    @pytest.mark.asyncio
    async def test_circuit_open_does_not_trigger_event(self, pool_manager):
        """Test that CircuitOpenError alone does not trigger event (needs final failure)."""
        mock_pool = MagicMock()
        mock_pool.name = "test-provider"
        mock_pool.health_status.value = "unhealthy"  # Circuit open
        mock_pool.config.supports = MagicMock(return_value=True)
        pool_manager._pools["test-provider"] = mock_pool

        label = Label(provider="test-provider", llm_type=LLMType.CHAT, model="test-model")
        request = MagicMock()
        request.label = label
        request.payload = {}
        request.priority = 1
        request.timeout = 30.0
        request.metadata = {}

        published_events = []

        async def capture_handler(event):
            published_events.append(event)

        pool_manager._event_bus.subscribe(LLMFailureEvent, capture_handler)

        # Should raise with no pool available
        with pytest.raises(AllProvidersFailedError):
            await pool_manager.execute(request)

        # No event should be published when all pools are skipped
        assert len(published_events) == 0
