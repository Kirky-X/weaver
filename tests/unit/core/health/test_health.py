# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for health check endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.endpoints.deps_registry import Endpoints
from api.endpoints.health import (
    check_neo4j_health,
    check_postgres_health,
    check_redis_health,
    health_check,
)
from container import set_container
from core.cache.redis import RedisClient
from core.db import PostgresPool
from core.db.neo4j import Neo4jPool


class TestCheckPostgresHealth:
    """Tests for PostgreSQL health check."""

    @pytest.fixture
    def mock_relational_pool(self):
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
    async def test_postgres_health_ok(self, mock_relational_pool):
        """Test PostgreSQL health check when connection is healthy."""
        result = await check_postgres_health(mock_relational_pool)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_postgres_health_timeout(self, mock_relational_pool):
        """Test PostgreSQL health check when connection times out."""
        # Mock execute to raise TimeoutError
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=TimeoutError())

        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_relational_pool.session_context = MagicMock(return_value=async_context)

        result = await check_postgres_health(mock_relational_pool)

        assert result["status"] == "timeout"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_postgres_health_error(self, mock_relational_pool):
        """Test PostgreSQL health check when connection fails."""
        # Mock execute to raise exception
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Connection refused"))

        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_relational_pool.session_context = MagicMock(return_value=async_context)

        result = await check_postgres_health(mock_relational_pool)

        assert result["status"] == "error"
        assert "latency_ms" in result
        assert "error" in result
        # After CWE-200 fix (vuln-0011): error is bool (True on failure);
        # detailed exception messages are logged server-side only.
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_postgres_health_latency_measurement(self, mock_relational_pool):
        """Test that PostgreSQL health check measures latency."""
        result = await check_postgres_health(mock_relational_pool)

        # Latency should be small (typically < 10ms in tests)
        assert result["latency_ms"] < 100


class TestCheckNeo4jHealth:
    """Tests for Neo4j health check."""

    @pytest.fixture
    def mock_graph_pool(self):
        """Create a mock Neo4j pool."""
        pool = MagicMock(spec=Neo4jPool)
        pool.execute_query = AsyncMock(return_value=[{"1": 1}])
        return pool

    @pytest.mark.asyncio
    async def test_neo4j_health_ok(self, mock_graph_pool):
        """Test Neo4j health check when connection is healthy."""
        result = await check_neo4j_health(mock_graph_pool)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0
        mock_graph_pool.execute_query.assert_called_once_with("RETURN 1")

    @pytest.mark.asyncio
    async def test_neo4j_health_timeout(self, mock_graph_pool):
        """Test Neo4j health check when connection times out."""
        mock_graph_pool.execute_query = AsyncMock(side_effect=TimeoutError())

        result = await check_neo4j_health(mock_graph_pool)

        assert result["status"] == "timeout"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_neo4j_health_error(self, mock_graph_pool):
        """Test Neo4j health check when connection fails."""
        mock_graph_pool.execute_query = AsyncMock(side_effect=Exception("ServiceUnavailable"))

        result = await check_neo4j_health(mock_graph_pool)

        assert result["status"] == "error"
        assert "latency_ms" in result
        assert "error" in result
        # After CWE-200 fix (vuln-0011): error is bool (True on failure);
        # detailed exception messages are logged server-side only.
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_neo4j_health_latency_measurement(self, mock_graph_pool):
        """Test that Neo4j health check measures latency."""
        result = await check_neo4j_health(mock_graph_pool)

        # Latency should be small (typically < 10ms in tests)
        assert result["latency_ms"] < 100


class TestCheckRedisHealth:
    """Tests for Redis health check."""

    @pytest.fixture
    def mock_cache_client(self):
        """Create a mock Redis client."""
        client = MagicMock(spec=RedisClient)
        client.ping = AsyncMock(return_value=True)
        return client

    @pytest.mark.asyncio
    async def test_redis_health_ok(self, mock_cache_client):
        """Test Redis health check when connection is healthy."""
        result = await check_redis_health(mock_cache_client)

        assert result["status"] == "ok"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0
        mock_cache_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_health_timeout(self, mock_cache_client):
        """Test Redis health check when connection times out."""
        mock_cache_client.ping = AsyncMock(side_effect=TimeoutError())

        result = await check_redis_health(mock_cache_client)

        assert result["status"] == "timeout"
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)

    @pytest.mark.asyncio
    async def test_redis_health_error(self, mock_cache_client):
        """Test Redis health check when connection fails."""
        mock_cache_client.ping = AsyncMock(side_effect=Exception("Connection refused"))

        result = await check_redis_health(mock_cache_client)

        assert result["status"] == "error"
        assert "latency_ms" in result
        assert "error" in result
        # After CWE-200 fix (vuln-0011): error is bool (True on failure);
        # detailed exception messages are logged server-side only.
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_redis_health_latency_measurement(self, mock_cache_client):
        """Test that Redis health check measures latency."""
        result = await check_redis_health(mock_cache_client)

        # Latency should be small (typically < 10ms in tests)
        assert result["latency_ms"] < 100


@pytest.mark.xdist_group(name="endpoints_deps")
class TestHealthCheck:
    """Tests for aggregated health check."""

    @pytest.fixture(autouse=True)
    def reset_container(self):
        """Reset global container before and after each test for isolation."""
        set_container(None)
        yield
        set_container(None)

    @staticmethod
    def _set_mock_container(relational_pool=None, graph_pool=None, cache_client=None):
        """Register a mock container returning the given pools.

        Mirrors the DI pattern used by ``health_check()`` which calls
        ``container.relational_pool()``, ``container.graph_pool()`` and
        ``container.cache_client()``, and reads ``relational_pool_type`` /
        ``graph_pool_type`` to determine the check keys.
        """
        container = MagicMock()
        container.relational_pool.return_value = relational_pool
        container.graph_pool.return_value = graph_pool
        container.cache_client.return_value = cache_client
        # health_check() uses these properties as the checks dict keys;
        # they must be real strings (mirroring Container's behavior) so
        # HealthCheckResponse validates and tests can assert by name.
        container.relational_pool_type = "postgres"
        container.graph_pool_type = "neo4j"
        set_container(container)

    @pytest.fixture
    def mock_relational_pool(self):
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
    def mock_graph_pool(self):
        """Create a mock Neo4j pool."""
        pool = MagicMock(spec=Neo4jPool)
        pool.execute_query = AsyncMock(return_value=[{"1": 1}])
        return pool

    @pytest.fixture
    def mock_cache_client(self):
        """Create a mock Redis client."""
        client = MagicMock(spec=RedisClient)
        client.ping = AsyncMock(return_value=True)
        return client

    @pytest.mark.asyncio
    async def test_all_healthy(self, mock_relational_pool, mock_graph_pool, mock_cache_client):
        """Test health check when all dependencies are healthy."""
        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "healthy"
        assert result.checks is not None
        assert result.checks["postgres"].status == "ok"
        assert result.checks["neo4j"].status == "ok"
        assert result.checks["redis"].status == "ok"

    @pytest.mark.asyncio
    async def test_postgres_unhealthy(
        self, mock_relational_pool, mock_graph_pool, mock_cache_client
    ):
        """Test health check when PostgreSQL is unhealthy."""
        # Make PostgreSQL fail
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Connection failed"))
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_relational_pool.session_context = MagicMock(return_value=async_context)

        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "error"
        assert result.checks["neo4j"].status == "ok"
        assert result.checks["redis"].status == "ok"

    @pytest.mark.asyncio
    async def test_neo4j_unhealthy(self, mock_relational_pool, mock_graph_pool, mock_cache_client):
        """Test health check when Neo4j is unhealthy."""
        mock_graph_pool.execute_query = AsyncMock(side_effect=Exception("ServiceUnavailable"))

        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "ok"
        assert result.checks["neo4j"].status == "error"
        assert result.checks["redis"].status == "ok"

    @pytest.mark.asyncio
    async def test_redis_unhealthy(self, mock_relational_pool, mock_graph_pool, mock_cache_client):
        """Test health check when Redis is unhealthy."""
        mock_cache_client.ping = AsyncMock(side_effect=Exception("Connection refused"))

        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "ok"
        assert result.checks["neo4j"].status == "ok"
        assert result.checks["redis"].status == "error"

    @pytest.mark.asyncio
    async def test_all_unhealthy(self, mock_relational_pool, mock_graph_pool, mock_cache_client):
        """Test health check when all dependencies are unhealthy."""
        # Make all services fail
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("Failed"))
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_relational_pool.session_context = MagicMock(return_value=async_context)

        mock_graph_pool.execute_query = AsyncMock(side_effect=Exception("Failed"))
        mock_cache_client.ping = AsyncMock(side_effect=Exception("Failed"))

        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "error"
        assert result.checks["neo4j"].status == "error"
        assert result.checks["redis"].status == "error"

    @pytest.mark.asyncio
    async def test_pools_not_initialized(self):
        """Test health check when pools are not initialized."""
        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "unavailable"
        assert result.checks["neo4j"].status == "unavailable"
        assert result.checks["redis"].status == "unavailable"
        # After CWE-200 fix (vuln-0011): error is a bool flag (True on failure);
        # detailed messages are logged server-side only, not exposed via API.
        assert result.checks["postgres"].error is True
        assert result.checks["neo4j"].error is True
        assert result.checks["redis"].error is True

    @pytest.mark.asyncio
    async def test_partial_pools_initialized(self, mock_graph_pool, mock_cache_client):
        """Test health check when only some pools are initialized."""
        self._set_mock_container(
            relational_pool=None,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "unavailable"
        assert result.checks["neo4j"].status == "ok"
        assert result.checks["redis"].status == "ok"

    @pytest.mark.asyncio
    async def test_timeout_scenarios(
        self, mock_relational_pool, mock_graph_pool, mock_cache_client
    ):
        """Test health check when dependencies timeout."""
        # Make all services timeout
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=TimeoutError())
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_relational_pool.session_context = MagicMock(return_value=async_context)

        mock_graph_pool.execute_query = AsyncMock(side_effect=TimeoutError())
        mock_cache_client.ping = AsyncMock(side_effect=TimeoutError())

        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "timeout"
        assert result.checks["neo4j"].status == "timeout"
        assert result.checks["redis"].status == "timeout"

    @pytest.mark.asyncio
    async def test_mixed_failure_scenarios(
        self, mock_relational_pool, mock_graph_pool, mock_cache_client
    ):
        """Test health check with mixed failure types."""
        # PostgreSQL: timeout
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=TimeoutError())
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_relational_pool.session_context = MagicMock(return_value=async_context)

        # Neo4j: error
        mock_graph_pool.execute_query = AsyncMock(side_effect=Exception("ServiceUnavailable"))

        # Redis: healthy (default)

        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        assert result.status == "unhealthy"
        assert result.checks["postgres"].status == "timeout"
        assert result.checks["neo4j"].status == "error"
        assert result.checks["redis"].status == "ok"

    @pytest.mark.asyncio
    async def test_latency_measured_for_all_checks(
        self, mock_relational_pool, mock_graph_pool, mock_cache_client
    ):
        """Test that latency is measured for all dependency checks."""
        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        # All checks should have latency measurements
        for check_name in ["postgres", "neo4j", "redis"]:
            assert result.checks[check_name].latency_ms is not None
            assert isinstance(result.checks[check_name].latency_ms, float)
            assert result.checks[check_name].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_error_messages_included(
        self, mock_relational_pool, mock_graph_pool, mock_cache_client
    ):
        """Test that error messages are included in failed checks."""
        # Make services fail with specific errors
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("PostgreSQL connection failed"))
        async_context = AsyncMock()
        async_context.__aenter__ = AsyncMock(return_value=mock_session)
        async_context.__aexit__ = AsyncMock(return_value=None)
        mock_relational_pool.session_context = MagicMock(return_value=async_context)

        mock_graph_pool.execute_query = AsyncMock(side_effect=Exception("Neo4j connection failed"))
        mock_cache_client.ping = AsyncMock(side_effect=Exception("Redis connection failed"))

        self._set_mock_container(
            relational_pool=mock_relational_pool,
            graph_pool=mock_graph_pool,
            cache_client=mock_cache_client,
        )

        result = await health_check()

        # After CWE-200 fix (vuln-0011): error is a bool flag (True on failure);
        # detailed exception messages are logged server-side only.
        assert result.checks["postgres"].error is True
        assert result.checks["neo4j"].error is True
        assert result.checks["redis"].error is True


class TestGlobalPoolSetters:
    """Tests for Endpoints class pool management."""

    @pytest.fixture(autouse=True)
    def cleanup_endpoints(self):
        """自动清理 Endpoints 状态,每个测试后执行"""
        # Reset before test
        Endpoints._relational_pool = None
        Endpoints._graph_pool = None
        Endpoints._cache = None

        yield  # 运行测试

        # Reset after test - ensure complete cleanup
        Endpoints._relational_pool = None
        Endpoints._graph_pool = None
        Endpoints._cache = None
        if hasattr(Endpoints, "_relational_pool_type"):
            Endpoints._relational_pool_type = None
        if hasattr(Endpoints, "_graph_pool_type"):
            Endpoints._graph_pool_type = None

    def test_set_relational_pool(self, cleanup_endpoints):
        """Test setting relational pool via Endpoints."""
        mock_pool = MagicMock(spec=PostgresPool)
        Endpoints._relational_pool = mock_pool

        assert Endpoints._relational_pool is mock_pool

    def test_set_graph_pool(self, cleanup_endpoints):
        """Test setting graph pool via Endpoints."""
        mock_pool = MagicMock(spec=Neo4jPool)
        Endpoints._graph_pool = mock_pool

        assert Endpoints._graph_pool is mock_pool

    def test_set_cache_client(self, cleanup_endpoints):
        """Test setting Redis client via Endpoints."""
        mock_client = MagicMock(spec=RedisClient)
        Endpoints._cache = mock_client

        assert Endpoints._cache is mock_client

    def test_set_pools_to_none(self, cleanup_endpoints):
        """Test setting pool references to None."""
        # First set to mock
        Endpoints._relational_pool = MagicMock(spec=PostgresPool)
        Endpoints._graph_pool = MagicMock(spec=Neo4jPool)
        Endpoints._cache = MagicMock(spec=RedisClient)

        # Then set to None
        Endpoints._relational_pool = None
        Endpoints._graph_pool = None
        Endpoints._cache = None

        assert Endpoints._relational_pool is None
        assert Endpoints._graph_pool is None
        assert Endpoints._cache is None
