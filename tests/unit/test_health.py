"""Unit tests for health check endpoints."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import text

from api.endpoints.health import (
    check_postgres_health,
    check_neo4j_health,
    check_redis_health,
    health_check,
    set_postgres_pool,
    set_neo4j_pool,
    set_redis_client,
)
from core.db.postgres import PostgresPool
from core.db.neo4j import Neo4jPool
from core.cache.redis import RedisClient


class TestCheckPostgresHealth:
    """Tests for PostgreSQL health check."""

    @pytest.fixture
    def mock_postgres_pool(self):
        """Create a mock PostgreSQL pool."""
        pool = MagicMock(spec=PostgresPool)

        # Create mock session
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=None)

        # Create async context manager for session_context
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        pool.session_context = MagicMock(return_value=async_context)

        return pool

    @pytest.mark.asyncio
    async def test_postgres_health_ok(self, mock_postgres_pool):
        """Test PostgreSQL health check when connection is healthy."""
        result = await check_postgres_health(mock_postgres_pool)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_postgres_health_timeout(self, mock_postgres_pool):
        """Test PostgreSQL health check when connection times out."""
        # Mock execute to raise TimeoutError
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=asyncio.TimeoutError())

        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        result = await check_postgres_health(mock_postgres_pool)

        assert result["status"] == "timeout"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_postgres_health_error(self, mock_postgres_pool):
        """Test PostgreSQL health check when connection fails."""
        # Mock execute to raise exception
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Connection refused"))

        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        result = await check_postgres_health(mock_postgres_pool)

        assert result["status"] == "error"
        assert "latency_ms" in result
        assert "error" in result
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_postgres_health_latency_measurement(self, mock_postgres_pool):
        """Test that PostgreSQL health check measures latency."""
        result = await check_postgres_health(mock_postgres_pool)

        # Latency should be small (typically < 10ms in tests)
        assert result["latency_ms"] < 100


class TestCheckNeo4jHealth:
    """Tests for Neo4j health check."""

    @pytest.fixture
    def mock_neo4j_pool(self):
        """Create a mock Neo4j pool."""
        pool = MagicMock(spec=Neo4jPool)
        pool.execute_query = AsyncMock(return_value=[{"1": 1}])
        return pool

    @pytest.mark.asyncio
    async def test_neo4j_health_ok(self, mock_neo4j_pool):
        """Test Neo4j health check when connection is healthy."""
        result = await check_neo4j_health(mock_neo4j_pool)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0
        mock_neo4j_pool.execute_query.assert_called_once_with("RETURN 1")

    @pytest.mark.asyncio
    async def test_neo4j_health_timeout(self, mock_neo4j_pool):
        """Test Neo4j health check when connection times out."""
        mock_neo4j_pool.execute_query = AsyncMock(side_effect=asyncio.TimeoutError())

        result = await check_neo4j_health(mock_neo4j_pool)

        assert result["status"] == "timeout"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_neo4j_health_error(self, mock_neo4j_pool):
        """Test Neo4j health check when connection fails."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=Exception("ServiceUnavailable")
        )

        result = await check_neo4j_health(mock_neo4j_pool)

        assert result["status"] == "error"
        assert "latency_ms" in result
        assert "error" in result
        assert "ServiceUnavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_neo4j_health_latency_measurement(self, mock_neo4j_pool):
        """Test that Neo4j health check measures latency."""
        result = await check_neo4j_health(mock_neo4j_pool)

        # Latency should be small (typically < 10ms in tests)
        assert result["latency_ms"] < 100


class TestCheckRedisHealth:
    """Tests for Redis health check."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = MagicMock(spec=RedisClient)
        client.client = MagicMock()
        client.client.ping = AsyncMock(return_value=True)
        return client

    @pytest.mark.asyncio
    async def test_redis_health_ok(self, mock_redis_client):
        """Test Redis health check when connection is healthy."""
        result = await check_redis_health(mock_redis_client)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0
        mock_redis_client.client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_health_timeout(self, mock_redis_client):
        """Test Redis health check when connection times out."""
        mock_redis_client.client.ping = AsyncMock(side_effect=asyncio.TimeoutError())

        result = await check_redis_health(mock_redis_client)

        assert result["status"] == "timeout"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_redis_health_error(self, mock_redis_client):
        """Test Redis health check when connection fails."""
        mock_redis_client.client.ping = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        result = await check_redis_health(mock_redis_client)

        assert result["status"] == "error"
        assert "latency_ms" in result
        assert "error" in result
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_redis_health_latency_measurement(self, mock_redis_client):
        """Test that Redis health check measures latency."""
        result = await check_redis_health(mock_redis_client)

        # Latency should be small (typically < 10ms in tests)
        assert result["latency_ms"] < 100


class TestHealthCheck:
    """Tests for aggregated health check."""

    @pytest.fixture(autouse=True)
    def reset_global_pools(self):
        """Reset global pool references before and after each test."""
        # Reset before test
        set_postgres_pool(None)
        set_neo4j_pool(None)
        set_redis_client(None)

        yield

        # Reset after test
        set_postgres_pool(None)
        set_neo4j_pool(None)
        set_redis_client(None)

    @pytest.fixture
    def mock_postgres_pool(self):
        """Create a mock PostgreSQL pool."""
        pool = MagicMock(spec=PostgresPool)
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=None)
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        pool.session_context = MagicMock(return_value=async_context)
        return pool

    @pytest.fixture
    def mock_neo4j_pool(self):
        """Create a mock Neo4j pool."""
        pool = MagicMock(spec=Neo4jPool)
        pool.execute_query = AsyncMock(return_value=[{"1": 1}])
        return pool

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = MagicMock(spec=RedisClient)
        client.client = MagicMock()
        client.client.ping = AsyncMock(return_value=True)
        return client

    @pytest.mark.asyncio
    async def test_all_healthy(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check when all dependencies are healthy."""
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert result["status"] == "healthy"
        assert "checks" in result
        assert result["checks"]["postgres"]["status"] == "ok"
        assert result["checks"]["neo4j"]["status"] == "ok"
        assert result["checks"]["redis"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_postgres_unhealthy(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check when PostgreSQL is unhealthy."""
        # Make PostgreSQL fail
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Connection failed"))
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "error"
        assert result["checks"]["neo4j"]["status"] == "ok"
        assert result["checks"]["redis"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_neo4j_unhealthy(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check when Neo4j is unhealthy."""
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=Exception("ServiceUnavailable")
        )

        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "ok"
        assert result["checks"]["neo4j"]["status"] == "error"
        assert result["checks"]["redis"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_redis_unhealthy(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check when Redis is unhealthy."""
        mock_redis_client.client.ping = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "ok"
        assert result["checks"]["neo4j"]["status"] == "ok"
        assert result["checks"]["redis"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_all_unhealthy(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check when all dependencies are unhealthy."""
        # Make all services fail
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Failed"))
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        mock_neo4j_pool.execute_query = AsyncMock(side_effect=Exception("Failed"))
        mock_redis_client.client.ping = AsyncMock(side_effect=Exception("Failed"))

        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "error"
        assert result["checks"]["neo4j"]["status"] == "error"
        assert result["checks"]["redis"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_pools_not_initialized(self):
        """Test health check when pools are not initialized."""
        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "unavailable"
        assert result["checks"]["neo4j"]["status"] == "unavailable"
        assert result["checks"]["redis"]["status"] == "unavailable"
        assert "not initialized" in result["checks"]["postgres"]["error"]
        assert "not initialized" in result["checks"]["neo4j"]["error"]
        assert "not initialized" in result["checks"]["redis"]["error"]

    @pytest.mark.asyncio
    async def test_partial_pools_initialized(
        self, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check when only some pools are initialized."""
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)
        # PostgreSQL pool not set

        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "unavailable"
        assert result["checks"]["neo4j"]["status"] == "ok"
        assert result["checks"]["redis"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_timeout_scenarios(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check when dependencies timeout."""
        # Make all services timeout
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=asyncio.TimeoutError())
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        mock_neo4j_pool.execute_query = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_redis_client.client.ping = AsyncMock(side_effect=asyncio.TimeoutError())

        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "timeout"
        assert result["checks"]["neo4j"]["status"] == "timeout"
        assert result["checks"]["redis"]["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_mixed_failure_scenarios(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test health check with mixed failure types."""
        # PostgreSQL: timeout
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=asyncio.TimeoutError())
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        # Neo4j: error
        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=Exception("ServiceUnavailable")
        )

        # Redis: healthy (default)

        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["postgres"]["status"] == "timeout"
        assert result["checks"]["neo4j"]["status"] == "error"
        assert result["checks"]["redis"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_latency_measured_for_all_checks(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test that latency is measured for all dependency checks."""
        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        # All checks should have latency measurements
        for check_name in ["postgres", "neo4j", "redis"]:
            assert "latency_ms" in result["checks"][check_name]
            assert isinstance(result["checks"][check_name]["latency_ms"], float)
            assert result["checks"][check_name]["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_error_messages_included(
        self, mock_postgres_pool, mock_neo4j_pool, mock_redis_client
    ):
        """Test that error messages are included in failed checks."""
        # Make services fail with specific errors
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=Exception("PostgreSQL connection failed")
        )
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_postgres_pool.session_context = MagicMock(return_value=async_context)

        mock_neo4j_pool.execute_query = AsyncMock(
            side_effect=Exception("Neo4j connection failed")
        )
        mock_redis_client.client.ping = AsyncMock(
            side_effect=Exception("Redis connection failed")
        )

        set_postgres_pool(mock_postgres_pool)
        set_neo4j_pool(mock_neo4j_pool)
        set_redis_client(mock_redis_client)

        result = await health_check()

        assert "PostgreSQL connection failed" in result["checks"]["postgres"]["error"]
        assert "Neo4j connection failed" in result["checks"]["neo4j"]["error"]
        assert "Redis connection failed" in result["checks"]["redis"]["error"]


class TestGlobalPoolSetters:
    """Tests for global pool setter functions."""

    def test_set_postgres_pool(self):
        """Test setting PostgreSQL pool reference."""
        mock_pool = MagicMock(spec=PostgresPool)
        set_postgres_pool(mock_pool)

        # Import the global variable to check
        from api.endpoints.health import _postgres_pool

        assert _postgres_pool is mock_pool

    def test_set_neo4j_pool(self):
        """Test setting Neo4j pool reference."""
        mock_pool = MagicMock(spec=Neo4jPool)
        set_neo4j_pool(mock_pool)

        from api.endpoints.health import _neo4j_pool

        assert _neo4j_pool is mock_pool

    def test_set_redis_client(self):
        """Test setting Redis client reference."""
        mock_client = MagicMock(spec=RedisClient)
        set_redis_client(mock_client)

        from api.endpoints.health import _redis_client

        assert _redis_client is mock_client

    def test_set_pools_to_none(self):
        """Test setting pool references to None."""
        # First set to mock
        set_postgres_pool(MagicMock(spec=PostgresPool))
        set_neo4j_pool(MagicMock(spec=Neo4jPool))
        set_redis_client(MagicMock(spec=RedisClient))

        # Then set to None
        set_postgres_pool(None)
        set_neo4j_pool(None)
        set_redis_client(None)

        from api.endpoints.health import _postgres_pool, _neo4j_pool, _redis_client

        assert _postgres_pool is None
        assert _neo4j_pool is None
        assert _redis_client is None