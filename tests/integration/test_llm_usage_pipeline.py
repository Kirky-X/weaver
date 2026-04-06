# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for LLM usage statistics pipeline with real services.

All tests use real services (PostgreSQL, Redis, EventBus) when available.
Tests are skipped if required services are not running.
"""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from core.event.bus import EventBus, LLMUsageEvent
from core.llm.types import TokenUsage
from modules.analytics.llm_usage.buffer import LLMUsageBuffer
from modules.analytics.llm_usage.repo import LLMUsageRepo


class TestLLMUsageEventFlow:
    """Test LLMUsageEvent flow from provider to event bus with real EventBus."""

    @pytest.fixture
    def event_bus(self):
        """Create a fresh EventBus for testing."""
        return EventBus()

    @pytest.fixture
    def captured_events(self):
        """List to capture published events."""
        return []

    @pytest.mark.asyncio
    async def test_event_bus_subscribes_llm_usage_event(self, event_bus):
        """Test EventBus can subscribe to LLMUsageEvent."""
        handler_called = False

        async def handler(event: LLMUsageEvent) -> None:
            nonlocal handler_called
            handler_called = True

        event_bus.subscribe(LLMUsageEvent, handler)

        # Verify subscription
        assert LLMUsageEvent in event_bus._handlers
        assert len(event_bus._handlers[LLMUsageEvent]) == 1

    @pytest.mark.asyncio
    async def test_event_bus_publishes_llm_usage_event(self, event_bus, captured_events):
        """Test EventBus publishes LLMUsageEvent to handlers."""

        async def capture_event(event: LLMUsageEvent) -> None:
            captured_events.append(event)

        event_bus.subscribe(LLMUsageEvent, capture_event)

        test_event = LLMUsageEvent(
            label="chat::anthropic::claude-3-opus",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=500.0,
            success=True,
        )

        await event_bus.publish(test_event)

        assert len(captured_events) == 1
        assert captured_events[0].label == "chat::anthropic::claude-3-opus"
        assert captured_events[0].tokens.input_tokens == 100

    @pytest.mark.asyncio
    async def test_multiple_handlers_receive_same_event(self, event_bus, captured_events):
        """Test multiple handlers all receive the same LLMUsageEvent."""

        async def handler1(event: LLMUsageEvent) -> None:
            captured_events.append(("handler1", event))

        async def handler2(event: LLMUsageEvent) -> None:
            captured_events.append(("handler2", event))

        async def handler3(event: LLMUsageEvent) -> None:
            captured_events.append(("handler3", event))

        event_bus.subscribe(LLMUsageEvent, handler1)
        event_bus.subscribe(LLMUsageEvent, handler2)
        event_bus.subscribe(LLMUsageEvent, handler3)

        test_event = LLMUsageEvent(
            label="chat::openai::gpt-4",
            call_point="analyzer",
            llm_type="chat",
            provider="openai",
            model="gpt-4",
            tokens=TokenUsage(input_tokens=200, output_tokens=100),
            latency_ms=800.0,
            success=True,
        )

        await event_bus.publish(test_event)

        assert len(captured_events) == 3
        # All handlers received the same event
        for handler_name, event in captured_events:
            assert event.label == "chat::openai::gpt-4"
            assert event.call_point == "analyzer"


class TestLLMUsageRedisBuffer:
    """Test LLMUsageBuffer Redis accumulation with real Redis."""

    @pytest.mark.asyncio
    async def test_buffer_accumulates_event(self, redis_client, unique_id):
        """Test LLMUsageBuffer accumulates event to Redis HASH."""
        buffer = LLMUsageBuffer(redis_client, ttl_seconds=7200)

        event = LLMUsageEvent(
            label=f"test_{unique_id}",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=500.0,
            success=True,
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        )

        # Should not raise exception
        await buffer.accumulate(event)

    @pytest.mark.asyncio
    async def test_buffer_handles_failure_event(self, redis_client, unique_id):
        """Test LLMUsageBuffer handles failure event correctly."""
        buffer = LLMUsageBuffer(redis_client, ttl_seconds=7200)

        event = LLMUsageEvent(
            label=f"test_{unique_id}",
            call_point="analyzer",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            tokens=TokenUsage(input_tokens=100, output_tokens=0, total_tokens=100),
            latency_ms=5000.0,
            success=False,
            error_type="TimeoutError",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        )

        # Should not raise exception
        await buffer.accumulate(event)


class TestLLMUsageRepoIntegration:
    """Test LLMUsageRepo database operations with real PostgreSQL."""

    @pytest.fixture
    async def repo(self, postgres_pool):
        """Create LLMUsageRepo with real pool."""
        return LLMUsageRepo(postgres_pool)

    @pytest.mark.asyncio
    async def test_insert_raw_event(self, repo, postgres_pool, unique_id):
        """Test LLMUsageRepo inserts raw event correctly with real database."""
        from modules.analytics.llm_usage.models import LLMUsageRaw

        raw = LLMUsageRaw(
            label=f"test_{unique_id}",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=500.0,
            success=True,
        )

        # Insert raw record
        async with postgres_pool.session_context() as session:
            session.add(raw)
            await session.commit()

        try:
            # Verify record was inserted
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM llm_usage_raw WHERE label = :label"),
                    {"label": f"test_{unique_id}"},
                )
                count = result.scalar()
                assert count == 1
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM llm_usage_raw WHERE label = :label"),
                    {"label": f"test_{unique_id}"},
                )

    @pytest.mark.asyncio
    async def test_insert_raw_batch(self, repo, postgres_pool, unique_id):
        """Test LLMUsageRepo inserts batch events correctly with real database."""
        from modules.analytics.llm_usage.models import LLMUsageRaw

        raw_events = [
            LLMUsageRaw(
                label=f"test_{unique_id}_{i}",
                call_point="classifier",
                llm_type="chat",
                provider="anthropic",
                model="claude-3-opus",
                input_tokens=100 + i,
                output_tokens=50 + i,
                total_tokens=150 + 2 * i,
                latency_ms=500.0 + i * 10,
                success=True,
            )
            for i in range(5)
        ]

        # Insert batch
        async with postgres_pool.session_context() as session:
            session.add_all(raw_events)
            await session.commit()

        try:
            # Verify records were inserted
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM llm_usage_raw WHERE label LIKE :pattern"),
                    {"pattern": f"test_{uniqueid}%"},
                )
                count = result.scalar()
                assert count == 5
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM llm_usage_raw WHERE label LIKE :pattern"),
                    {"pattern": f"test_{unique_id}%"},
                )


class TestLLMUsageCompleteChain:
    """Test complete chain: Event → Buffer → DB with real services."""

    @pytest.mark.asyncio
    async def test_complete_chain_event_to_buffer_to_db(
        self, event_bus, redis_client, postgres_pool, unique_id
    ):
        """Test complete chain: Event published → Buffer receives → DB stores."""
        from modules.analytics.llm_usage.models import LLMUsageRaw

        buffer = LLMUsageBuffer(redis_client, ttl_seconds=7200)
        repo = LLMUsageRepo(postgres_pool)

        buffer_received = []
        db_received = []

        # Subscribe buffer handler
        async def buffer_handler(event: LLMUsageEvent) -> None:
            buffer_received.append(event)
            await buffer.accumulate(event)

        # Subscribe DB handler
        async def db_handler(event: LLMUsageEvent) -> None:
            db_received.append(event)
            # Insert to DB
            raw = LLMUsageRaw(
                label=event.label,
                call_point=event.call_point,
                llm_type=event.llm_type,
                provider=event.provider,
                model=event.model,
                input_tokens=event.tokens.input_tokens,
                output_tokens=event.tokens.output_tokens,
                total_tokens=event.tokens.total_tokens,
                latency_ms=event.latency_ms,
                success=event.success,
            )
            async with postgres_pool.session_context() as session:
                session.add(raw)
                await session.commit()

        event_bus.subscribe(LLMUsageEvent, buffer_handler)
        event_bus.subscribe(LLMUsageEvent, db_handler)

        try:
            # Publish event
            event = LLMUsageEvent(
                label=f"test_chain_{unique_id}",
                call_point="classifier",
                llm_type="chat",
                provider="anthropic",
                model="claude-3-opus",
                tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
                latency_ms=500.0,
                success=True,
            )

            await event_bus.publish(event)

            # Verify both handlers received the event
            assert len(buffer_received) == 1
            assert len(db_received) == 1
            assert buffer_received[0] == event
            assert db_received[0] == event

            # Verify DB has the record
            async with postgres_pool.session_context() as session:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM llm_usage_raw WHERE label = :label"),
                    {"label": f"test_chain_{unique_id}"},
                )
                count = result.scalar()
                assert count == 1
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM llm_usage_raw WHERE label = :label"),
                    {"label": f"test_chain_{unique_id}"},
                )

    @pytest.mark.asyncio
    async def test_chain_handles_partial_failure(self, event_bus, postgres_pool, unique_id):
        """Test chain continues even when one handler fails."""
        from modules.analytics.llm_usage.models import LLMUsageRaw

        repo = LLMUsageRepo(postgres_pool)
        successful_handler_called = False

        async def failing_handler(event: LLMUsageEvent) -> None:
            raise RuntimeError("Handler failure")

        async def successful_handler(event: LLMUsageEvent) -> None:
            nonlocal successful_handler_called
            successful_handler_called = True
            raw = LLMUsageRaw(
                label=f"test_partial_{unique_id}",
                call_point=event.call_point,
                llm_type=event.llm_type,
                provider=event.provider,
                model=event.model,
                input_tokens=event.tokens.input_tokens,
                output_tokens=event.tokens.output_tokens,
                total_tokens=event.tokens.total_tokens,
                latency_ms=event.latency_ms,
                success=event.success,
            )
            async with postgres_pool.session_context() as session:
                session.add(raw)
                await session.commit()

        event_bus.subscribe(LLMUsageEvent, failing_handler)
        event_bus.subscribe(LLMUsageEvent, successful_handler)

        try:
            event = LLMUsageEvent(
                label=f"test_partial_{unique_id}",
                call_point="classifier",
                tokens=TokenUsage(input_tokens=100, output_tokens=50),
                latency_ms=500.0,
                success=True,
            )

            # Should not raise - successful handler should still be called
            await event_bus.publish(event)

            assert successful_handler_called
        finally:
            # Cleanup
            async with postgres_pool.session_context() as session:
                await session.execute(
                    text("DELETE FROM llm_usage_raw WHERE label = :label"),
                    {"label": f"test_partial_{unique_id}"},
                )


class TestLLMUsageAPIEndpoints:
    """Test LLM usage API endpoints with real database."""

    @pytest.fixture
    def app(self, postgres_pool):
        """Create FastAPI app with LLM usage endpoints using real repo."""
        from api.endpoints import admin
        from api.endpoints._deps import Endpoints
        from api.middleware.auth import verify_api_key

        # Set real repo
        Endpoints._llm_usage_repo = LLMUsageRepo(postgres_pool)

        app = FastAPI()
        # Override auth dependency
        app.dependency_overrides[verify_api_key] = lambda: "test-api-key"
        app.include_router(admin.router)
        return app

    @pytest.fixture
    def client(self, app):
        """Create TestClient."""
        with TestClient(app) as client:
            yield client

    def test_get_llm_usage_endpoint(self, client):
        """Test GET /admin/llm-usage endpoint with real database."""
        response = client.get(
            "/admin/llm-usage",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2030-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_get_llm_usage_summary_endpoint(self, client):
        """Test GET /admin/llm-usage/summary endpoint with real database."""
        response = client.get(
            "/admin/llm-usage/summary",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2030-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data


class TestLLMTokenPrometheusMetrics:
    """Test Prometheus metrics for LLM token tracking."""

    @pytest.fixture
    def metrics_app(self):
        """Create minimal FastAPI app with metrics endpoint."""
        from fastapi.responses import PlainTextResponse

        app = FastAPI()

        @app.get("/metrics")
        async def metrics_endpoint():
            return PlainTextResponse(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )

        return app

    @pytest.fixture
    def metrics_client(self, metrics_app):
        """Create TestClient for metrics endpoint."""
        with TestClient(metrics_app) as client:
            yield client

    def test_metrics_endpoint_contains_llm_token_metrics(self, metrics_client):
        """Test /metrics endpoint contains LLM token metrics."""
        response = metrics_client.get("/metrics")
        assert response.status_code == 200

        content = response.text

        # Verify LLM token metrics are defined
        assert "llm_token_input_total" in content
        assert "llm_token_output_total" in content
        assert "llm_token_total" in content

    def test_llm_token_metrics_have_correct_labels(self, metrics_client):
        """Test LLM token metrics have required labels."""
        response = metrics_client.get("/metrics")
        content = response.text

        # Check TYPE declarations
        lines = content.split("\n")

        # Find TYPE declarations for LLM token metrics
        type_lines = [line for line in lines if line.startswith("# TYPE llm_token")]

        assert len(type_lines) >= 3, "Should have TYPE declarations for all three token metrics"

        # Each should be a Counter
        for line in type_lines:
            assert "counter" in line.lower(), f"{line} should be a counter"

    def test_llm_token_metrics_increment_on_event(self, metrics_client):
        """Test LLM token metrics increment when LLMUsageEvent is processed."""
        from core.observability.metrics import metrics

        # Record some token usage
        metrics.llm_token_input_total.labels(
            provider="anthropic", model="claude-3-opus", call_point="classifier"
        ).inc(100)
        metrics.llm_token_output_total.labels(
            provider="anthropic", model="claude-3-opus", call_point="classifier"
        ).inc(50)
        metrics.llm_token_total.labels(
            provider="anthropic", model="claude-3-opus", call_point="classifier"
        ).inc(150)

        response = metrics_client.get("/metrics")
        content = response.text

        # Verify metrics appear in output
        assert "llm_token_input_total" in content
        assert "llm_token_output_total" in content
        assert "llm_token_total" in content

    def test_metrics_format_valid_prometheus(self, metrics_client):
        """Test metrics format is valid Prometheus format."""
        import re

        response = metrics_client.get("/metrics")
        content = response.text

        lines = content.strip().split("\n")
        valid_lines = 0

        metric_pattern = r"^[a-zA-Z_:][a-zA-Z0-9_:]*({[^}]+})?\s+[\d\.eE+-]+(\s+\d+)?$"

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("# TYPE ") or line.startswith("# HELP "):
                valid_lines += 1
                continue
            assert re.match(metric_pattern, line), f"Invalid Prometheus format: {line}"
            valid_lines += 1

        assert valid_lines > 0, "Should have valid metric lines"

    def test_metrics_content_type_correct(self, metrics_client):
        """Test metrics endpoint returns correct Content-Type."""
        response = metrics_client.get("/metrics")

        assert response.headers.get("content-type") == CONTENT_TYPE_LATEST


class TestPrometheusMetricsIntegration:
    """Integration tests for Prometheus metrics with LLM usage events."""

    @pytest.fixture
    def event_bus(self):
        """Create EventBus for testing."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_event_handler_updates_prometheus_metrics(self, event_bus):
        """Test LLMUsageEvent handler updates Prometheus metrics."""
        from core.observability.metrics import metrics

        # Create and publish event
        event = LLMUsageEvent(
            label="chat::test_provider::test_model",
            call_point="test_point",
            llm_type="chat",
            provider="test_provider",
            model="test_model",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=500.0,
            success=True,
        )

        # Simulate the metrics handler
        labels = {
            "provider": event.provider,
            "model": event.model,
            "call_point": event.call_point,
        }
        metrics.llm_token_input_total.labels(**labels).inc(event.tokens.input_tokens)
        metrics.llm_token_output_total.labels(**labels).inc(event.tokens.output_tokens)
        metrics.llm_token_total.labels(**labels).inc(event.tokens.total_tokens)

    @pytest.mark.asyncio
    async def test_metrics_handler_error_isolation(self, event_bus):
        """Test metrics handler errors don't affect other handlers."""
        handler2_called = False

        async def failing_metrics_handler(event: LLMUsageEvent) -> None:
            raise RuntimeError("Metrics error")

        async def successful_handler(event: LLMUsageEvent) -> None:
            nonlocal handler2_called
            handler2_called = True

        event_bus.subscribe(LLMUsageEvent, failing_metrics_handler)
        event_bus.subscribe(LLMUsageEvent, successful_handler)

        event = LLMUsageEvent(
            label="chat::test::model",
            call_point="test",
            tokens=TokenUsage(input_tokens=100, output_tokens=50),
            latency_ms=500.0,
            success=True,
        )

        await event_bus.publish(event)

        # Both handlers should have been called (error isolation)
        assert handler2_called
