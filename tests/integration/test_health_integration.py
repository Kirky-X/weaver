# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for health check endpoints with real service connections."""

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from api.endpoints._deps import Endpoints
from api.endpoints.health import (
    check_neo4j_health,
    check_postgres_health,
    check_redis_health,
    health_check,
)


def create_test_app():
    """Create a minimal FastAPI app for testing health endpoint."""
    app = FastAPI()

    @app.get("/health")
    async def health_check_endpoint():
        """Health check endpoint with dependency checks."""
        result = await health_check()
        if result.status != "healthy":
            raise HTTPException(status_code=503, detail=result.model_dump())
        return result.model_dump()

    return app


class TestHealthEndpointIntegration:
    """Integration tests for health check endpoint with real services."""

    @pytest.fixture(autouse=True)
    def reset_global_pools(self):
        """Reset global pool references before and after each test."""
        Endpoints._postgres = None
        Endpoints._neo4j = None
        Endpoints._redis = None
        yield
        Endpoints._postgres = None
        Endpoints._neo4j = None
        Endpoints._redis = None

    @pytest.fixture
    def app(self):
        """Create FastAPI app for testing."""
        return create_test_app()

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_200_when_all_services_healthy(
        self,
        app,
        postgres_pool,
        neo4j_pool,
        redis_client,
    ):
        """Test health endpoint returns 200 when all services are healthy."""
        # Set global pools with real connections
        Endpoints._postgres = postgres_pool
        Endpoints._neo4j = neo4j_pool
        Endpoints._redis = redis_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

        # Assert status code
        assert response.status_code == 200

        # Assert response format
        data = response.json()
        assert "status" in data
        assert "checks" in data
        assert data["status"] == "healthy"

        # Assert all checks present
        assert "postgres" in data["checks"]
        assert "neo4j" in data["checks"]
        assert "redis" in data["checks"]

        # Assert all checks healthy
        assert data["checks"]["postgres"]["status"] == "ok"
        assert data["checks"]["neo4j"]["status"] == "ok"
        assert data["checks"]["redis"]["status"] == "ok"

        # Assert latency measured
        for check_name in ["postgres", "neo4j", "redis"]:
            assert "latency_ms" in data["checks"][check_name]
            assert isinstance(data["checks"][check_name]["latency_ms"], (int, float))
            assert data["checks"][check_name]["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_health_endpoint_response_format(
        self,
        app,
        postgres_pool,
        neo4j_pool,
        redis_client,
    ):
        """Test health endpoint response format is correct."""
        # Set global pools
        Endpoints._postgres = postgres_pool
        Endpoints._neo4j = neo4j_pool
        Endpoints._redis = redis_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

        # Assert response headers
        assert response.headers["content-type"] == "application/json"

        # Assert response structure
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)

        # Assert each check has required fields
        for check_name in ["postgres", "neo4j", "redis"]:
            check = data["checks"][check_name]
            assert "status" in check
            assert "latency_ms" in check
            assert isinstance(check["latency_ms"], (int, float))

    @pytest.mark.asyncio
    async def test_health_endpoint_handles_pools_not_initialized(self, app):
        """Test health endpoint handles pools not initialized gracefully."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

        # Assert status code
        assert response.status_code == 503

        # Assert unavailable status
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert data["detail"]["checks"]["postgres"]["status"] == "unavailable"
        assert data["detail"]["checks"]["neo4j"]["status"] == "unavailable"
        assert data["detail"]["checks"]["redis"]["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_health_endpoint_performance(
        self,
        app,
        postgres_pool,
        neo4j_pool,
        redis_client,
    ):
        """Test health endpoint responds within reasonable time."""
        import time

        # Set global pools
        Endpoints._postgres = postgres_pool
        Endpoints._neo4j = neo4j_pool
        Endpoints._redis = redis_client

        # Measure response time
        start_time = time.time()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
        end_time = time.time()

        # Assert response is successful
        assert response.status_code == 200

        # Assert response time is reasonable (< 2 seconds for real services)
        response_time = end_time - start_time
        assert response_time < 2.0, f"Response time too slow: {response_time}s"

        # Assert latency measured in checks
        data = response.json()
        for check_name in ["postgres", "neo4j", "redis"]:
            assert "latency_ms" in data["checks"][check_name]
            # Latency should be reasonable for real services
            assert data["checks"][check_name]["latency_ms"] < 1000


class TestIndividualHealthChecks:
    """Integration tests for individual health check functions."""

    @pytest.mark.asyncio
    async def test_check_postgres_health_with_real_pool(self, postgres_pool):
        """Test PostgreSQL health check with real connection."""
        result = await check_postgres_health(postgres_pool)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_check_neo4j_health_with_real_pool(self, neo4j_pool):
        """Test Neo4j health check with real connection."""
        result = await check_neo4j_health(neo4j_pool)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_check_redis_health_with_real_client(self, redis_client):
        """Test Redis health check with real connection."""
        result = await check_redis_health(redis_client)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_check_postgres_health_handles_none_pool(self):
        """Test PostgreSQL health check handles None pool gracefully."""
        result = await check_postgres_health(None)

        assert result["status"] == "error"
        assert "error" in result
        assert result["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_check_neo4j_health_handles_none_pool(self):
        """Test Neo4j health check handles None pool gracefully."""
        result = await check_neo4j_health(None)

        assert result["status"] == "error"
        assert "error" in result
        assert result["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_check_redis_health_handles_none_client(self):
        """Test Redis health check handles None client gracefully."""
        result = await check_redis_health(None)

        assert result["status"] == "error"
        assert "error" in result
        assert result["latency_ms"] >= 0
