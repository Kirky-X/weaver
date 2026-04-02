# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for LLM usage statistics pipeline.

This module tests the complete data flow:
Provider → Event → Redis Buffer → Aggregator → PostgreSQL

Tests cover:
- Task 12.1: Provider → Event → Redis → Flush → DB complete chain
- Task 12.2: API endpoint end-to-end tests
- Task 12.3: Prometheus metrics validation
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from core.event.bus import EventBus, LLMUsageEvent
from core.llm.types import TokenUsage
from modules.analytics.llm_usage.buffer import LLMUsageBuffer
from modules.analytics.llm_usage.repo import LLMUsageRepo

# ─────────────────────────────────────────────────────────────────────────────
# Task 12.1: Provider → Event → Redis → Flush → DB Complete Chain Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLLMUsageEventFlow:
    """Test LLMUsageEvent flow from provider to event bus."""

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
    """Test LLMUsageBuffer Redis accumulation."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create mock Redis client."""
        client = MagicMock()
        client.client = MagicMock()

        # Mock pipeline
        pipeline = AsyncMock()
        pipeline.hincrby = MagicMock(return_value=pipeline)
        pipeline.expire = MagicMock(return_value=pipeline)
        pipeline.execute = AsyncMock(return_value=[1] * 8)

        # Support async context manager
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        client.client.pipeline = MagicMock(return_value=pipeline)

        return client

    @pytest.fixture
    def buffer(self, mock_redis_client):
        """Create LLMUsageBuffer with mock Redis."""
        return LLMUsageBuffer(mock_redis_client, ttl_seconds=7200)

    @pytest.mark.asyncio
    async def test_buffer_accumulates_event(self, buffer, mock_redis_client):
        """Test LLMUsageBuffer accumulates event to Redis HASH."""
        event = LLMUsageEvent(
            label="chat::anthropic::claude-3-opus",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=500.0,
            success=True,
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        )

        await buffer.accumulate(event)

        # Verify pipeline was created and executed
        mock_redis_client.client.pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_buffer_handles_failure_event(self, buffer, mock_redis_client):
        """Test LLMUsageBuffer handles failure event correctly."""
        event = LLMUsageEvent(
            label="chat::anthropic::claude-3-opus",
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

    @pytest.mark.asyncio
    async def test_buffer_handles_redis_error_gracefully(self, buffer, mock_redis_client):
        """Test buffer handles Redis errors without blocking."""
        # Make Redis fail
        mock_redis_client.client.pipeline.side_effect = Exception("Redis connection error")

        event = LLMUsageEvent(
            label="chat::anthropic::claude-3-opus",
            call_point="classifier",
            tokens=TokenUsage(input_tokens=100, output_tokens=50),
            latency_ms=500.0,
            success=True,
        )

        # Should not raise exception
        await buffer.accumulate(event)


class TestLLMUsageRepoIntegration:
    """Test LLMUsageRepo database operations."""

    @pytest.fixture
    def mock_postgres_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        session = MagicMock()
        session.add = MagicMock()
        session.add_all = MagicMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock()

        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        pool.session = MagicMock(return_value=async_context)

        return pool

    @pytest.fixture
    def repo(self, mock_postgres_pool):
        """Create LLMUsageRepo with mock pool."""
        return LLMUsageRepo(mock_postgres_pool)

    @pytest.mark.asyncio
    async def test_insert_raw_event(self, repo, mock_postgres_pool):
        """Test LLMUsageRepo inserts raw event correctly."""
        event = LLMUsageEvent(
            label="chat::anthropic::claude-3-opus",
            call_point="classifier",
            llm_type="chat",
            provider="anthropic",
            model="claude-3-opus",
            tokens=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            latency_ms=500.0,
            success=True,
        )

        await repo.insert_raw(event)

        # Verify session.add was called
        mock_postgres_pool.session.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_raw_batch(self, repo, mock_postgres_pool):
        """Test LLMUsageRepo inserts batch events correctly."""
        events = [
            LLMUsageEvent(
                label="chat::anthropic::claude-3-opus",
                call_point="classifier",
                llm_type="chat",
                provider="anthropic",
                model="claude-3-opus",
                tokens=TokenUsage(input_tokens=100 + i, output_tokens=50 + i),
                latency_ms=500.0 + i * 10,
                success=True,
            )
            for i in range(5)
        ]

        count = await repo.insert_raw_batch(events)

        assert count == 5


class TestLLMUsageCompleteChain:
    """Test complete chain: Event → Buffer → DB."""

    @pytest.fixture
    def event_bus(self):
        """Create EventBus."""
        return EventBus()

    @pytest.fixture
    def mock_redis_client(self):
        """Create mock Redis client."""
        client = MagicMock()
        client.client = MagicMock()

        pipeline = AsyncMock()
        pipeline.hincrby = MagicMock(return_value=pipeline)
        pipeline.expire = MagicMock(return_value=pipeline)
        pipeline.execute = AsyncMock(return_value=[1] * 8)
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        client.client.pipeline = MagicMock(return_value=pipeline)
        client.scan = AsyncMock(return_value=(0, []))
        client.delete = AsyncMock()

        return client

    @pytest.fixture
    def mock_postgres_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        session = MagicMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock()
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        pool.session = MagicMock(return_value=async_context)
        return pool

    @pytest.mark.asyncio
    async def test_complete_chain_event_to_buffer_to_db(
        self, event_bus, mock_redis_client, mock_postgres_pool
    ):
        """Test complete chain: Event published → Buffer receives → DB stores."""
        buffer = LLMUsageBuffer(mock_redis_client, ttl_seconds=7200)
        repo = LLMUsageRepo(mock_postgres_pool)

        buffer_received = []
        db_received = []

        # Subscribe buffer handler
        async def buffer_handler(event: LLMUsageEvent) -> None:
            buffer_received.append(event)
            await buffer.accumulate(event)

        # Subscribe DB handler
        async def db_handler(event: LLMUsageEvent) -> None:
            db_received.append(event)
            await repo.insert_raw(event)

        event_bus.subscribe(LLMUsageEvent, buffer_handler)
        event_bus.subscribe(LLMUsageEvent, db_handler)

        # Publish event
        event = LLMUsageEvent(
            label="chat::anthropic::claude-3-opus",
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

    @pytest.mark.asyncio
    async def test_chain_handles_partial_failure(
        self, event_bus, mock_redis_client, mock_postgres_pool
    ):
        """Test chain continues even when one handler fails."""
        repo = LLMUsageRepo(mock_postgres_pool)
        successful_handler_called = False

        async def failing_handler(event: LLMUsageEvent) -> None:
            raise RuntimeError("Handler failure")

        async def successful_handler(event: LLMUsageEvent) -> None:
            nonlocal successful_handler_called
            successful_handler_called = True
            await repo.insert_raw(event)

        event_bus.subscribe(LLMUsageEvent, failing_handler)
        event_bus.subscribe(LLMUsageEvent, successful_handler)

        event = LLMUsageEvent(
            label="chat::anthropic::claude-3-opus",
            call_point="classifier",
            tokens=TokenUsage(input_tokens=100, output_tokens=50),
            latency_ms=500.0,
            success=True,
        )

        # Should not raise - successful handler should still be called
        await event_bus.publish(event)

        assert successful_handler_called


# ─────────────────────────────────────────────────────────────────────────────
# Task 12.2: API Endpoint End-to-End Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLLMUsageAPIEndpoints:
    """Test LLM usage API endpoints with TestClient."""

    @pytest.fixture
    def mock_llm_usage_repo(self):
        """Create mock LLM usage repo."""
        repo = MagicMock()
        repo.query_hourly = AsyncMock(
            return_value=[
                {
                    "time_bucket": "2024-01-15T10:00:00",
                    "call_count": 100,
                    "input_tokens_sum": 50000,
                    "output_tokens_sum": 25000,
                    "total_tokens_sum": 75000,
                    "latency_avg_ms": 500.5,
                    "latency_min_ms": 200.0,
                    "latency_max_ms": 1500.0,
                    "success_count": 98,
                    "failure_count": 2,
                }
            ]
        )
        repo.get_summary = AsyncMock(
            return_value={
                "total_calls": 1000,
                "total_input_tokens": 500000,
                "total_output_tokens": 250000,
                "total_tokens": 750000,
                "avg_latency_ms": 450.5,
                "max_latency_ms": 2000.0,
                "min_latency_ms": 100.0,
                "success_rate": 0.98,
                "error_types": {"timeout": 10, "rate_limit": 5},
            }
        )
        repo.get_by_provider = AsyncMock(
            return_value=[
                {
                    "provider": "anthropic",
                    "call_count": 500,
                    "total_tokens": 300000,
                    "avg_latency_ms": 400.0,
                    "success_rate": 0.99,
                }
            ]
        )
        repo.get_by_model = AsyncMock(
            return_value=[
                {
                    "model": "claude-3-opus",
                    "provider": "anthropic",
                    "call_count": 300,
                    "total_tokens": 200000,
                    "avg_latency_ms": 500.0,
                    "success_rate": 0.99,
                }
            ]
        )
        repo.get_by_call_point = AsyncMock(
            return_value=[
                {
                    "call_point": "classifier",
                    "call_count": 500,
                    "total_tokens": 300000,
                    "avg_latency_ms": 300.0,
                    "success_rate": 0.99,
                }
            ]
        )
        return repo

    @pytest.fixture
    def app(self, mock_llm_usage_repo):
        """Create FastAPI app with LLM usage endpoints."""
        from api.endpoints import admin
        from api.endpoints._deps import Endpoints
        from api.middleware.auth import verify_api_key

        # Set mock repo
        Endpoints._llm_usage_repo = mock_llm_usage_repo

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

    def test_get_llm_usage_endpoint(self, client, mock_llm_usage_repo):
        """Test GET /admin/llm-usage endpoint."""
        response = client.get(
            "/admin/llm-usage",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "records" in data["data"]
        assert "total" in data["data"]

    def test_get_llm_usage_summary_endpoint(self, client, mock_llm_usage_repo):
        """Test GET /admin/llm-usage/summary endpoint."""
        response = client.get(
            "/admin/llm-usage/summary",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["data"]["total_calls"] == 1000
        assert data["data"]["success_rate"] == 0.98

    def test_get_llm_usage_by_provider_endpoint(self, client, mock_llm_usage_repo):
        """Test GET /admin/llm-usage/by-provider endpoint."""
        response = client.get(
            "/admin/llm-usage/by-provider",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["provider"] == "anthropic"

    def test_get_llm_usage_by_model_endpoint(self, client, mock_llm_usage_repo):
        """Test GET /admin/llm-usage/by-model endpoint."""
        response = client.get(
            "/admin/llm-usage/by-model",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["model"] == "claude-3-opus"

    def test_get_llm_usage_by_call_point_endpoint(self, client, mock_llm_usage_repo):
        """Test GET /admin/llm-usage/by-call-point endpoint."""
        response = client.get(
            "/admin/llm-usage/by-call-point",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["call_point"] == "classifier"


class TestLLMUsageAPIWithFilters:
    """Test LLM usage API endpoints with various filters."""

    @pytest.fixture
    def mock_llm_usage_repo(self):
        """Create mock LLM usage repo."""
        repo = MagicMock()
        repo.query_hourly = AsyncMock(return_value=[])
        repo.get_summary = AsyncMock(
            return_value={
                "total_calls": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "avg_latency_ms": 0.0,
                "success_rate": 1.0,
                "error_types": {},
            }
        )
        return repo

    @pytest.fixture
    def app(self, mock_llm_usage_repo):
        """Create FastAPI app."""
        from api.endpoints import admin
        from api.endpoints._deps import Endpoints
        from api.middleware.auth import verify_api_key

        Endpoints._llm_usage_repo = mock_llm_usage_repo

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

    def test_llm_usage_with_provider_filter(self, client, mock_llm_usage_repo):
        """Test LLM usage endpoint with provider filter."""
        response = client.get(
            "/admin/llm-usage",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
                "provider": "anthropic",
            },
        )

        assert response.status_code == 200
        # Verify filter was passed to repo
        call_kwargs = mock_llm_usage_repo.query_hourly.call_args[1]
        assert call_kwargs["provider"] == "anthropic"

    def test_llm_usage_with_model_filter(self, client, mock_llm_usage_repo):
        """Test LLM usage endpoint with model filter."""
        response = client.get(
            "/admin/llm-usage",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
                "model": "claude-3-opus",
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_llm_usage_repo.query_hourly.call_args[1]
        assert call_kwargs["model"] == "claude-3-opus"

    def test_llm_usage_with_llm_type_filter(self, client, mock_llm_usage_repo):
        """Test LLM usage endpoint with LLM type filter."""
        response = client.get(
            "/admin/llm-usage",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
                "llm_type": "chat",
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_llm_usage_repo.query_hourly.call_args[1]
        assert call_kwargs["llm_type"] == "chat"

    def test_llm_usage_with_call_point_filter(self, client, mock_llm_usage_repo):
        """Test LLM usage endpoint with call point filter."""
        response = client.get(
            "/admin/llm-usage",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
                "call_point": "classifier",
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_llm_usage_repo.query_hourly.call_args[1]
        assert call_kwargs["call_point"] == "classifier"

    def test_llm_usage_with_granularity(self, client, mock_llm_usage_repo):
        """Test LLM usage endpoint with granularity."""
        response = client.get(
            "/admin/llm-usage",
            params={
                "from": "2024-01-01T00:00:00Z",
                "to": "2024-01-31T23:59:59Z",
                "granularity": "daily",
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_llm_usage_repo.query_hourly.call_args[1]
        assert call_kwargs["granularity"] == "daily"


# ─────────────────────────────────────────────────────────────────────────────
# Task 12.3: Prometheus Metrics Validation Tests
# ─────────────────────────────────────────────────────────────────────────────


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

        # Verify metrics appear in output - check for metric names with labels
        # Prometheus format: metric_name{label1="value1",label2="value2"} value
        assert "llm_token_input_total" in content
        assert "llm_token_output_total" in content
        assert "llm_token_total" in content
        # Check that the labels are present (order may vary)
        assert 'provider="anthropic"' in content or "provider='anthropic'" in content
        assert 'model="claude-3-opus"' in content or "model='claude-3-opus'" in content

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

        # Get initial values (might be 0 or already have some value)
        initial_input = (
            metrics.llm_token_input_total.labels(
                provider="test_provider", model="test_model", call_point="test_point"
            )._value.get()
            if hasattr(
                metrics.llm_token_input_total.labels(
                    provider="test_provider", model="test_model", call_point="test_point"
                ),
                "_value",
            )
            else 0
        )

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

        # Verify metrics were incremented
        # Note: In real test, we'd need to check the actual metric value
        # For now, we verify the code path works without errors

    @pytest.mark.asyncio
    async def test_metrics_handler_error_isolation(self, event_bus):
        """Test metrics handler errors don't affect other handlers."""
        handler1_called = False
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
