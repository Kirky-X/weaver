# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for LLM failure logging — full chain from event to DB."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from core.event.bus import EventBus, LLMFailureEvent
from modules.analytics.llm_failure.repo import LLMFailureRepo


class TestLLMFailureEventChain:
    """Integration tests for the LLM failure → EventBus → Repo chain."""

    @pytest.fixture
    def repo(self, postgres_pool):
        """Create LLMFailureRepo with real pool."""
        return LLMFailureRepo(postgres_pool)

    @pytest.mark.asyncio
    async def test_llm_failure_event_published_to_event_bus(self, event_bus):
        """Test LLMFailureEvent can be published and received via EventBus."""
        received_events = []

        async def handler(event):
            received_events.append(event)

        event_bus.subscribe(LLMFailureEvent, handler)

        await event_bus.publish(
            LLMFailureEvent(
                call_point="classifier",
                provider="openai",
                error_type="RateLimitError",
                error_detail="Rate limit exceeded",
                latency_ms=1500.0,
                article_id=None,
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
    async def test_event_bus_handler_records_failure_to_repo(
        self, repo, event_bus, postgres_pool, unique_id
    ):
        """Test EventBus handler correctly records failure to LLMFailureRepo."""

        async def handle(event):
            await repo.record(event)

        event_bus.subscribe(LLMFailureEvent, handle)

        await event_bus.publish(
            LLMFailureEvent(
                call_point=f"analyzer_{unique_id}",
                provider="anthropic",
                error_type="ApiError",
                error_detail="Invalid API key",
                latency_ms=300.0,
                article_id=None,
                task_id="task-456",
                attempt=0,
                fallback_tried=False,
            )
        )

        # Verify record was created
        async with postgres_pool.session_context() as session:
            result = await session.execute(
                text(
                    "SELECT call_point, provider, error_type FROM llm_failures WHERE call_point = :cp"
                ),
                {"cp": f"analyzer_{unique_id}"},
            )
            row = result.fetchone()
            assert row is not None
            assert row.call_point == f"analyzer_{unique_id}"
            assert row.provider == "anthropic"

        # Cleanup
        async with postgres_pool.session_context() as session:
            await session.execute(
                text("DELETE FROM llm_failures WHERE call_point = :cp"),
                {"cp": f"analyzer_{unique_id}"},
            )

    @pytest.mark.asyncio
    async def test_multiple_failures_recorded_separately(
        self, repo, event_bus, postgres_pool, unique_id
    ):
        """Test multiple failure events are recorded as separate rows."""

        async def handle(event):
            await repo.record(event)

        event_bus.subscribe(LLMFailureEvent, handle)

        for i in range(3):
            await event_bus.publish(
                LLMFailureEvent(
                    call_point=f"node_{unique_id}_{i}",
                    provider="openai",
                    error_type="Timeout",
                    error_detail=f"Timeout on attempt {i}",
                    latency_ms=30000.0,
                    article_id=None,
                    task_id=f"task-{i}",
                    attempt=i,
                    fallback_tried=i > 0,
                )
            )

        # Verify 3 records were created
        async with postgres_pool.session_context() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM llm_failures WHERE call_point LIKE :pattern"),
                {"pattern": f"node_{unique_id}%"},
            )
            count = result.scalar()
            assert count == 3

        # Cleanup
        async with postgres_pool.session_context() as session:
            await session.execute(
                text("DELETE FROM llm_failures WHERE call_point LIKE :pattern"),
                {"pattern": f"node_{unique_id}%"},
            )

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_records_only(self, repo, postgres_pool, unique_id):
        """Test cleanup_older_than only deletes records older than cutoff."""

        # Create test records
        async def handle(event):
            await repo.record(event)

        event_bus = EventBus()
        event_bus.subscribe(LLMFailureEvent, handle)

        await event_bus.publish(
            LLMFailureEvent(
                call_point=f"cleanup_test_{unique_id}",
                provider="openai",
                error_type="Test",
                error_detail="Test",
                latency_ms=0.0,
                article_id=None,
                task_id="test",
                attempt=0,
                fallback_tried=False,
            )
        )

        # Verify the record was created
        async with postgres_pool.session_context() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM llm_failures WHERE call_point = :cp"),
                {"cp": f"cleanup_test_{unique_id}"},
            )
            assert result.scalar() == 1

        # Manually backdate the record so it is older than the cutoff
        async with postgres_pool.session_context() as session:
            await session.execute(
                text(
                    "UPDATE llm_failures SET created_at = created_at - INTERVAL '2 days' "
                    "WHERE call_point = :cp"
                ),
                {"cp": f"cleanup_test_{unique_id}"},
            )
            await session.commit()

        # Cleanup with days=1 should delete the backdated record
        removed = await repo.cleanup_older_than(days=1)
        assert removed >= 1

        # Verify record was deleted
        async with postgres_pool.session_context() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM llm_failures WHERE call_point = :cp"),
                {"cp": f"cleanup_test_{unique_id}"},
            )
            assert result.scalar() == 0

    @pytest.mark.asyncio
    async def test_handler_error_does_not_propagate(self, event_bus):
        """Test that handler errors are logged but do not crash the event bus."""
        article_id = str(uuid4())

        async def failing_handler(event):
            raise RuntimeError("Database connection failed")

        async def succeeding_handler(event):
            pass

        event_bus.subscribe(LLMFailureEvent, failing_handler)
        event_bus.subscribe(LLMFailureEvent, succeeding_handler)

        # Publishing should not raise even if one handler fails
        await event_bus.publish(
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
        """Test Container.startup() wires event bus to LLM failure handler."""
        import inspect

        from container import Container, _handle_llm_failure_async

        # Verify the async handler function exists and is callable
        assert callable(_handle_llm_failure_async)

        # Verify Container.startup contains the wiring
        source = inspect.getsource(Container.startup)

        assert "_llm_failure_repo" in source
        assert "_event_bus.subscribe" in source
        assert "LLMFailureEvent" in source
        assert "_llm_failure_cleanup_thread" in source
        assert ".start()" in source

    @pytest.mark.asyncio
    async def test_container_startup_starts_cleanup_thread(self):
        """Test Container.startup() starts the cleanup thread on startup."""
        import inspect

        from container import Container

        source = inspect.getsource(Container.startup)

        # Verify the cleanup thread is started immediately in startup
        assert "LLMFailureCleanupThread" in source
        assert ".start()" in source
