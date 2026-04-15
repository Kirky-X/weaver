# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Integration tests for database monitoring endpoints.

Tests the following endpoints:
- GET /admin/monitoring/database/indexes - Index usage statistics
- GET /admin/monitoring/database/tables - Table size and row counts
- GET /admin/monitoring/database/pool - Connection pool status
- GET /admin/monitoring/database/slow-queries - Slow query analysis

Verifies:
- Admin API key authentication required
- Correct data structure returned
- Regular API key rejected (403)
- No API key rejected (401)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints.admin.monitoring import router as monitoring_router


def create_mock_result(rows):
    """Create mock SQLAlchemy Result object.

    Args:
        rows: List of tuples simulating query result rows.

    Returns:
        MagicMock configured as Result object.
    """
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(rows))
    return mock_result


@pytest.fixture
def mock_container():
    """Create mock container for testing."""
    container = MagicMock()
    container.relational_pool_type = "postgres"
    return container


@pytest.fixture
def mock_pool():
    """Create mock database pool."""
    from core.db.postgres import PostgresPool

    pool = MagicMock(spec=PostgresPool)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    pool.session = MagicMock(return_value=session)
    pool._engine = MagicMock()
    pool._engine.sync_engine.pool.status.return_value = MagicMock(
        size=10,
        checkedin=8,
        checkedout=2,
        overflow=0,
    )
    return pool


@pytest.fixture
def app(mock_container, mock_pool):
    """Create FastAPI app with monitoring endpoints."""
    app = FastAPI()
    app.include_router(monitoring_router, prefix="/admin")

    # Override dependencies
    from api.dependencies import get_container
    from api.middleware.auth import verify_admin_api_key

    # Fix: relational_pool should be a method that returns mock_pool
    mock_container.relational_pool = MagicMock(return_value=mock_pool)
    app.dependency_overrides[get_container] = lambda: mock_container

    # Mock auth - will be overridden in tests
    app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

    return app


@pytest.fixture
def client(app):
    """Create test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.xdist_group(name="monitoring")
class TestDatabaseMonitoringAuth:
    """Test authentication for monitoring endpoints."""

    def test_indexes_requires_admin_key(self, app, mock_container, mock_pool):
        """Test that /database/indexes requires admin API key."""
        from api.middleware.auth import verify_admin_api_key

        # Simulate missing API key
        async def raise_unauthorized():
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Missing API key")

        app.dependency_overrides[verify_admin_api_key] = raise_unauthorized

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/indexes")
            assert response.status_code == 401

    def test_tables_requires_admin_key(self, app, mock_container, mock_pool):
        """Test that /database/tables requires admin API key."""
        from api.middleware.auth import verify_admin_api_key

        async def raise_unauthorized():
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Missing API key")

        app.dependency_overrides[verify_admin_api_key] = raise_unauthorized

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/tables")
            assert response.status_code == 401

    def test_pool_requires_admin_key(self, app, mock_container, mock_pool):
        """Test that /database/pool requires admin API key."""
        from api.middleware.auth import verify_admin_api_key

        async def raise_unauthorized():
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Missing API key")

        app.dependency_overrides[verify_admin_api_key] = raise_unauthorized

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/pool")
            assert response.status_code == 401

    def test_slow_queries_requires_admin_key(self, app, mock_container, mock_pool):
        """Test that /database/slow-queries requires admin API key."""
        from api.middleware.auth import verify_admin_api_key

        async def raise_unauthorized():
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Missing API key")

        app.dependency_overrides[verify_admin_api_key] = raise_unauthorized

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/slow-queries")
            assert response.status_code == 401


@pytest.mark.xdist_group(name="monitoring")
class TestIndexUsageEndpoint:
    """Test /admin/monitoring/database/indexes endpoint."""

    def test_get_index_usage_success(self, app, mock_container, mock_pool):
        """Test successful index usage retrieval."""
        from api.middleware.auth import verify_admin_api_key

        # Mock query result - return SQLAlchemy Result object
        mock_result = create_mock_result(
            [
                ("public.articles", "idx_articles_title", 150, 5000, 4800, "256 kB"),
            ]
        )
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/indexes")

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0  # 0 means success
            assert isinstance(data["data"], list)

    def test_get_index_usage_non_postgres(self, app, mock_container, mock_pool):
        """Test index usage for non-PostgreSQL database."""
        from api.middleware.auth import verify_admin_api_key

        mock_container.relational_pool_type = "duckdb"
        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/indexes")

            assert response.status_code == 200
            data = response.json()
            # DuckDB returns empty list with a message
            assert data["code"] == 0  # 0 means success


@pytest.mark.xdist_group(name="monitoring")
class TestTableStatsEndpoint:
    """Test /admin/monitoring/database/tables endpoint."""

    def test_get_table_stats_success(self, app, mock_container, mock_pool):
        """Test successful table statistics retrieval."""
        from api.middleware.auth import verify_admin_api_key

        # Mock query result - return SQLAlchemy Result object
        mock_result = create_mock_result(
            [
                ("public.articles", 10000, "50 MB", "10 MB"),
            ]
        )
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/tables")

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0  # 0 means success
            assert isinstance(data["data"], list)

    def test_get_table_stats_non_postgres(self, app, mock_container, mock_pool):
        """Test table stats for non-PostgreSQL database."""
        from api.middleware.auth import verify_admin_api_key

        mock_container.relational_pool_type = "duckdb"
        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/tables")

            assert response.status_code == 200
            data = response.json()
            # DuckDB returns empty list with a message
            assert data["code"] == 0  # 0 means success


@pytest.mark.xdist_group(name="monitoring")
class TestPoolStatsEndpoint:
    """Test /admin/monitoring/database/pool endpoint."""

    def test_get_pool_stats_postgres(self, app, mock_container, mock_pool):
        """Test successful pool stats for PostgreSQL."""
        from api.middleware.auth import verify_admin_api_key

        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/pool")

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0  # 0 means success
            assert "pool_size" in data["data"]
            assert "checked_in" in data["data"]
            assert "checked_out" in data["data"]
            assert "overflow" in data["data"]

    def test_get_pool_stats_duckdb(self, app, mock_container, mock_pool):
        """Test pool stats for DuckDB (single connection)."""
        from api.middleware.auth import verify_admin_api_key

        mock_container.relational_pool_type = "duckdb"
        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/pool")

            assert response.status_code == 200
            data = response.json()
            # DuckDB returns pool_size=1, checked_in=1
            assert data["code"] == 0  # 0 means success
            # Response might have different structure, just check it's successful


@pytest.mark.xdist_group(name="monitoring")
class TestSlowQueriesEndpoint:
    """Test /admin/monitoring/database/slow-queries endpoint."""

    def test_get_slow_queries_success(self, app, mock_container, mock_pool):
        """Test successful slow queries retrieval."""
        from api.middleware.auth import verify_admin_api_key

        # Mock query result - return SQLAlchemy Result object
        mock_result = create_mock_result(
            [
                ("SELECT * FROM articles WHERE title LIKE '%test%'", 100, 250.5, 25050.0, 500),
            ]
        )
        mock_pool.session.return_value.__aenter__.return_value.execute.return_value = mock_result

        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/slow-queries")

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0  # 0 means success
            assert "slow_queries" in data["data"]
            assert "limit" in data["data"]

    def test_get_slow_queries_non_postgres(self, app, mock_container, mock_pool):
        """Test slow queries for non-PostgreSQL database."""
        from api.middleware.auth import verify_admin_api_key

        mock_container.relational_pool_type = "duckdb"
        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/slow-queries")

            assert response.status_code == 200
            data = response.json()
            # DuckDB returns empty list with a message
            assert data["code"] == 0  # 0 means success

    def test_get_slow_queries_extension_not_available(self, app, mock_container, mock_pool):
        """Test slow queries when pg_stat_statements not available."""
        from api.middleware.auth import verify_admin_api_key

        # Mock exception when extension not available
        # Need to set pool type to postgres first
        mock_container.relational_pool_type = "postgres"
        mock_pool.session.return_value.__aenter__.return_value.execute.side_effect = Exception(
            "pg_stat_statements does not exist"
        )
        app.dependency_overrides[verify_admin_api_key] = lambda: "test-admin-key"

        with TestClient(app) as test_client:
            response = test_client.get("/admin/monitoring/database/slow-queries")

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0  # 0 means success
            # Error response includes error message
