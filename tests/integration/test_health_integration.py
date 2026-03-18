"""Integration tests for health check endpoints with real service connections."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from api.endpoints.health import health_check as check_health
from api.endpoints.health import (
    set_postgres_pool,
    set_neo4j_pool,
    set_redis_client,
)


def create_test_app():
    """Create a minimal FastAPI app for testing health endpoint."""
    app = FastAPI()

    @app.get("/health")
    async def health_check_endpoint():
        """Health check endpoint with dependency checks."""
        result = await check_health()
        if result["status"] != "healthy":
            raise HTTPException(status_code=503, detail=result)
        return result

    return app


class TestHealthEndpointIntegration:
    """Integration tests for health check endpoint with FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def reset_global_pools(self):
        """Reset global pool references before and after each test."""
        set_postgres_pool(None)
        set_neo4j_pool(None)
        set_redis_client(None)
        yield
        set_postgres_pool(None)
        set_neo4j_pool(None)
        set_redis_client(None)

    @pytest.fixture
    def mock_postgres_pool(self):
        """Create mock PostgreSQL pool."""
        pool = MagicMock()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        pool.session_context = MagicMock(return_value=async_context)
        return pool

    @pytest.fixture
    def mock_neo4j_pool(self):
        """Create mock Neo4j pool."""
        pool = MagicMock()
        pool.execute_query = AsyncMock(return_value=[{"1": 1}])
        return pool

    @pytest.fixture
    def mock_redis_client(self):
        """Create mock Redis client."""
        client = MagicMock()
        client.client = MagicMock()
        client.client.ping = AsyncMock(return_value=True)
        return client

    @pytest.fixture
    def app(self):
        """Create FastAPI app for testing."""
        return create_test_app()

    @pytest.fixture
    def client(self, app):
        """Create TestClient for testing."""
        with TestClient(app) as client:
            yield client

    def test_health_endpoint_returns_200_when_all_services_healthy(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint returns 200 when all services are healthy."""
        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

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

    def test_health_endpoint_returns_503_when_postgres_unhealthy(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint returns 503 when PostgreSQL is unhealthy."""
        # Make PostgreSQL fail
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=Exception("Connection refused"))
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

        # Assert status code
        assert response.status_code == 503

        # Assert response format
        data = response.json()
        assert "detail" in data
        assert "status" in data["detail"]
        assert "checks" in data["detail"]
        assert data["detail"]["status"] == "unhealthy"

        # Assert PostgreSQL failed but others healthy
        assert data["detail"]["checks"]["postgres"]["status"] == "error"
        assert data["detail"]["checks"]["neo4j"]["status"] == "ok"
        assert data["detail"]["checks"]["redis"]["status"] == "ok"

    def test_health_endpoint_returns_503_when_neo4j_unhealthy(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint returns 503 when Neo4j is unhealthy."""
        # Make Neo4j fail
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=Exception("ServiceUnavailable")
        )

        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

        # Assert status code
        assert response.status_code == 503

        # Assert response format
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert data["detail"]["checks"]["postgres"]["status"] == "ok"
        assert data["detail"]["checks"]["neo4j"]["status"] == "error"
        assert data["detail"]["checks"]["redis"]["status"] == "ok"

    def test_health_endpoint_returns_503_when_redis_unhealthy(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint returns 503 when Redis is unhealthy."""
        # Make Redis fail
        mock_redis_client.client.ping = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

        # Assert status code
        assert response.status_code == 503

        # Assert response format
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert data["detail"]["checks"]["postgres"]["status"] == "ok"
        assert data["detail"]["checks"]["neo4j"]["status"] == "ok"
        assert data["detail"]["checks"]["redis"]["status"] == "error"

    def test_health_endpoint_returns_503_when_all_services_unhealthy(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint returns 503 when all services are unhealthy."""
        # Make all services fail
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=Exception("Failed"))
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Failed"))
        mock_redis_client.client.ping = AsyncMock(side_effect=Exception("Failed"))

        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

        # Assert status code
        assert response.status_code == 503

        # Assert response format
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert data["detail"]["checks"]["postgres"]["status"] == "error"
        assert data["detail"]["checks"]["neo4j"]["status"] == "error"
        assert data["detail"]["checks"]["redis"]["status"] == "error"

    def test_health_endpoint_handles_timeout_gracefully(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint handles timeout gracefully."""
        # Make all services timeout
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=asyncio.TimeoutError())
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        mock_neo4j_pool.execute_query = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_redis_client.client.ping = AsyncMock(side_effect=asyncio.TimeoutError())

        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

        # Assert status code
        assert response.status_code == 503

        # Assert timeout status reported
        data = response.json()
        assert data["detail"]["checks"]["postgres"]["status"] == "timeout"
        assert data["detail"]["checks"]["neo4j"]["status"] == "timeout"
        assert data["detail"]["checks"]["redis"]["status"] == "timeout"

    def test_health_endpoint_handles_pools_not_initialized(self, client):
        """Test health endpoint handles pools not initialized gracefully."""
        # Pools are not set (None)

        # Make request
        response = client.get("/health")

        # Assert status code
        assert response.status_code == 503

        # Assert unavailable status
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert data["detail"]["checks"]["postgres"]["status"] == "unavailable"
        assert data["detail"]["checks"]["neo4j"]["status"] == "unavailable"
        assert data["detail"]["checks"]["redis"]["status"] == "unavailable"

    def test_health_endpoint_response_format(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint response format is correct."""
        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

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

    def test_health_endpoint_degraded_service_behavior(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint properly reports degraded service."""
        # Make PostgreSQL timeout (degraded but not down)
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=asyncio.TimeoutError())
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        # Neo4j and Redis healthy
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

        # Should still return 503 because one service is unhealthy
        assert response.status_code == 503

        # Assert response shows partial degradation
        data = response.json()
        assert data["detail"]["status"] == "unhealthy"
        assert data["detail"]["checks"]["postgres"]["status"] == "timeout"
        assert data["detail"]["checks"]["neo4j"]["status"] == "ok"
        assert data["detail"]["checks"]["redis"]["status"] == "ok"

    def test_health_endpoint_error_messages_included(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint includes error messages in failed checks."""
        # Make services fail with specific errors
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=Exception("PostgreSQL connection failed")
        )
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=Exception("Neo4j service unavailable")
        )
        mock_redis_client.client.ping = AsyncMock(
            side_effect=Exception("Redis connection refused")
        )

        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make request
        response = client.get("/health")

        # Assert error messages present
        data = response.json()
        assert "PostgreSQL connection failed" in data["detail"]["checks"]["postgres"]["error"]
        assert "Neo4j service unavailable" in data["detail"]["checks"]["neo4j"]["error"]
        assert "Redis connection refused" in data["detail"]["checks"]["redis"]["error"]

    def test_health_endpoint_concurrent_requests(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint handles concurrent requests correctly."""
        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Make multiple concurrent requests
        import concurrent.futures

        def make_request():
            return client.get("/health")

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            results = [future.result() for future in futures]

        # All requests should succeed
        for response in results:
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"

    def test_health_endpoint_performance(
        self,
        client,
        mock_postgres_pool,
        mock_neo4j_pool,
        mock_redis_client,
    ):
        """Test health endpoint responds within reasonable time."""
        import time

        # Set global pools
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        # Measure response time
        start_time = time.time()
        response = client.get("/health")
        end_time = time.time()

        # Assert response is successful
        assert response.status_code == 200

        # Assert response time is reasonable (< 1 second for mocked services)
        response_time = end_time - start_time
        assert response_time < 1.0, f"Response time too slow: {response_time}s"

        # Assert latency measured in checks
        data = response.json()
        for check_name in ["postgres", "neo4j", "redis"]:
            assert "latency_ms" in data["checks"][check_name]
            # Latency should be very small for mocked services
            assert data["checks"][check_name]["latency_ms"] < 100