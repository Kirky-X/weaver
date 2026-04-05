# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for Memory Pipeline integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event.bus import EventBus, MemoryIngestEvent


@pytest.fixture
def event_bus():
    """Create event bus."""
    return EventBus()


@pytest.fixture
def mock_memory_service():
    """Create mock memory service."""
    service = MagicMock()
    service.ingest = AsyncMock()
    return service


class TestMemoryPipelineIntegration:
    """Tests for memory pipeline event integration."""

    def test_memory_ingest_event_creation(self):
        """Test MemoryIngestEvent can be created with required fields."""
        event = MemoryIngestEvent(
            article_id="test-article-123",
            state={"title": "Test Article", "content": "Test content"},
        )

        assert event.article_id == "test-article-123"
        assert event.state["title"] == "Test Article"
        assert event.timestamp is not None

    @pytest.mark.asyncio
    async def test_event_bus_publishes_memory_event(self, event_bus):
        """Test EventBus can publish and handle MemoryIngestEvent."""
        received_events = []

        async def handler(event: MemoryIngestEvent):
            received_events.append(event)

        event_bus.subscribe(MemoryIngestEvent, handler)

        event = MemoryIngestEvent(
            article_id="test-article-456",
            state={"title": "Another Test"},
        )
        await event_bus.publish(event)

        assert len(received_events) == 1
        assert received_events[0].article_id == "test-article-456"

    @pytest.mark.asyncio
    async def test_container_memory_event_handler(self, event_bus, mock_memory_service):
        """Test container memory event handler integration."""

        # Simulate container's event handler setup
        async def handle_memory_ingest(event: MemoryIngestEvent):
            if mock_memory_service is None:
                return
            await mock_memory_service.ingest(event.state)

        event_bus.subscribe(MemoryIngestEvent, handle_memory_ingest)

        # Publish event
        event = MemoryIngestEvent(
            article_id="test-article-789",
            state={"title": "Handler Test"},
        )
        await event_bus.publish(event)

        mock_memory_service.ingest.assert_called_once()
        call_args = mock_memory_service.ingest.call_args[0][0]
        assert call_args["title"] == "Handler Test"

    @pytest.mark.asyncio
    async def test_memory_handler_safe_skip_on_none_service(self, event_bus):
        """Test handler safely skips when memory service is None."""
        memory_service = None
        call_count = 0

        async def handle_memory_ingest(event: MemoryIngestEvent):
            nonlocal call_count
            if memory_service is None:
                return
            call_count += 1
            await memory_service.ingest(event.state)

        event_bus.subscribe(MemoryIngestEvent, handle_memory_ingest)

        event = MemoryIngestEvent(
            article_id="test-article-none",
            state={"title": "None Service Test"},
        )
        await event_bus.publish(event)

        # Handler should have returned early without incrementing
        assert call_count == 0
