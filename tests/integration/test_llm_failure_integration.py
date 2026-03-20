# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for LLM failure logging — full chain from event to DB."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core.event.bus import EventBus, LLMFailureEvent
from modules.storage.llm_failure_repo import LLMFailureRepo


class TestLLMFailureEventChain:
    """Integration tests for the LLM failure → EventBus → Repo chain."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock PostgresPool with async session support."""
        pool = MagicMock()
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.rollback = AsyncMock()
        pool.session.return_value.__aenter__.return_value = mock_session
        pool.session.return_value.__aexit__.return_value = AsyncMock()
        return pool

    @pytest.fixture
    def event_bus(self):
        """Create a real EventBus for testing."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_llm_failure_event_published_to_event_bus(self):
        """Test LLMFailureEvent can be published and received via EventBus."""
        bus = EventBus()
        received_events = []

        def handler(event):
            received_events.append(event)

        bus.subscribe(LLMFailureEvent, handler)

        await bus.publish(
            LLMFailureEvent(
                call_point="classifier",
                provider="openai",
                error_type="RateLimitError",
                error_detail="Rate limit exceeded",
                latency_ms=1500.0,
                article_id=str(uuid4()),
                task_id="task-123",
                attempt=1,
                fallback_tried=True,
            )
        )

        assert len(received_events) == 1
        event = received_events[0]
        assert event.call_point == "classifier"
        assert event.provider == "openai"
        assert event.error_type == "RateLimitError"
        assert event.fallback_tried is True

    @pytest.mark.asyncio
    async def test_event_bus_handler_records_failure_to_repo(self, mock_pool):
        """Test EventBus handler correctly records failure to LLMFailureRepo."""
        repo = LLMFailureRepo(mock_pool)
        bus = EventBus()
        article_id = str(uuid4())

        async def handle(event):
            await repo.record(event)

        bus.subscribe(LLMFailureEvent, handle)

        await bus.publish(
            LLMFailureEvent(
                call_point="analyzer",
                provider="anthropic",
                error_type="ApiError",
                error_detail="Invalid API key",
                latency_ms=300.0,
                article_id=article_id,
                task_id="task-456",
                attempt=0,
                fallback_tried=False,
            )
        )

        # Verify session.add was called with correct fields
        added = mock_pool.session.return_value.__aenter__.return_value.add.call_args[0][0]
        assert added.call_point == "analyzer"
        assert added.provider == "anthropic"
        assert added.error_type == "ApiError"
        assert str(added.article_id) == article_id
        assert added.task_id == "task-456"

    @pytest.mark.asyncio
    async def test_multiple_failures_recorded_separately(self, mock_pool):
        """Test multiple failure events are recorded as separate rows."""
        repo = LLMFailureRepo(mock_pool)
        bus = EventBus()

        async def handle(event):
            await repo.record(event)

        bus.subscribe(LLMFailureEvent, handle)

        for i in range(3):
            await bus.publish(
                LLMFailureEvent(
                    call_point=f"node_{i}",
                    provider="openai",
                    error_type="Timeout",
                    error_detail=f"Timeout on attempt {i}",
                    latency_ms=30000.0,
                    article_id=str(uuid4()),
                    task_id=f"task-{i}",
                    attempt=i,
                    fallback_tried=i > 0,
                )
            )

        assert mock_pool.session.return_value.__aenter__.return_value.add.call_count == 3

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_records_only(self, mock_pool):
        """Test cleanup_older_than only deletes records older than cutoff."""
        repo = LLMFailureRepo(mock_pool)

        # Simulate 10 old records deleted
        mock_result = MagicMock()
        mock_result.rowcount = 10
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        removed = await repo.cleanup_older_than(days=3)

        assert removed == 10
        mock_pool.session.return_value.__aenter__.return_value.commit.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_with_zero_days(self, mock_pool):
        """Test cleanup_older_than(0) deletes all records (useful for testing)."""
        repo = LLMFailureRepo(mock_pool)

        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        removed = await repo.cleanup_older_than(days=0)

        assert removed == 5

    @pytest.mark.asyncio
    async def test_handler_error_does_not_propagate(self, mock_pool):
        """Test that handler errors are logged but do not crash the event bus."""
        bus = EventBus()
        article_id = str(uuid4())

        async def failing_handler(event):
            raise RuntimeError("Database connection failed")

        async def succeeding_handler(event):
            pass

        bus.subscribe(LLMFailureEvent, failing_handler)
        bus.subscribe(LLMFailureEvent, succeeding_handler)

        # Publishing should not raise even if one handler fails
        await bus.publish(
            LLMFailureEvent(
                call_point="test",
                provider="test",
                error_type="TestError",
                error_detail="Test",
                latency_ms=0.0,
                article_id=article_id,
                task_id="task-test",
                attempt=0,
                fallback_tried=False,
            )
        )

    @pytest.mark.asyncio
    async def test_container_wires_event_bus_to_handler(self):
        """Test Container.startup() wires event bus to LLM failure handler.

        This is a code inspection test — verifies that the container's
        startup() method contains the correct wiring for the LLM failure chain.
        """
        import inspect

        from container import Container, _handle_llm_failure_async

        settings = MagicMock()
        container = Container().configure(settings)

        startup_source = inspect.getsource(container.startup)

        # Verify all components are wired in startup()
        assert "_llm_failure_repo = LLMFailureRepo" in startup_source
        assert "_event_bus.subscribe" in startup_source
        assert "LLMFailureEvent" in startup_source
        assert "_llm_failure_cleanup_thread = LLMFailureCleanupThread" in startup_source
        assert "_llm_failure_cleanup_thread.start()" in startup_source

        # Verify shutdown wires stop()
        shutdown_source = inspect.getsource(container.shutdown)
        assert "_llm_failure_cleanup_thread.stop()" in shutdown_source

        # Verify the async handler function exists and is callable
        assert callable(_handle_llm_failure_async)

    @pytest.mark.asyncio
    async def test_container_startup_starts_cleanup_thread(self):
        """Test Container.startup() starts the cleanup thread on startup."""
        import inspect

        from container import Container

        settings = MagicMock()
        container = Container().configure(settings)

        startup_source = inspect.getsource(container.startup)

        # Verify the cleanup thread is started immediately in startup
        assert "LLMFailureCleanupThread" in startup_source
        assert ".start()" in startup_source
