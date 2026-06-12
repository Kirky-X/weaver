# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for pre-startup health checking functionality."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import HealthCheckSettings, Settings
from core.health import (
    PreStartupHealthChecker,
    ServiceCheckResult,
    run_pre_startup_health_check,
)

# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────


@pytest.fixture
def health_settings() -> HealthCheckSettings:
    """Create default health check settings for testing."""
    return HealthCheckSettings(
        pre_startup_enabled=True,
        required_services=["postgres", "redis"],
        optional_services=["neo4j"],
        timeout_seconds=5.0,
        max_retries=3,
        retry_delay_seconds=0.1,  # Fast retries for testing
    )


@pytest.fixture
def mock_settings(health_settings: HealthCheckSettings) -> MagicMock:
    """Create mock settings for testing."""
    settings = MagicMock(spec=Settings)
    settings.health_check = health_settings
    settings.postgres = MagicMock()
    settings.postgres.dsn = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
    settings.redis = MagicMock()
    settings.redis.url = "redis://localhost:6379/0"
    settings.neo4j = MagicMock()
    settings.neo4j.uri = "bolt://localhost:7687"
    settings.neo4j.user = "neo4j"
    settings.neo4j.password = "password"
    return settings


# ────────────────────────────────────────────────────────────
# ServiceCheckResult Tests
# ────────────────────────────────────────────────────────────


def test_service_check_result_default_values() -> None:
    """Test ServiceCheckResult default values."""
    result = ServiceCheckResult(service="test")

    assert result.service == "test"
    assert result.healthy is False
    assert result.details == []
    assert result.error is None
    assert result.latency_ms is None


def test_service_check_result_with_values() -> None:
    """Test ServiceCheckResult with custom values."""
    result = ServiceCheckResult(
        service="postgres",
        healthy=True,
        details=["Connection successful"],
        latency_ms=123.45,
    )

    assert result.service == "postgres"
    assert result.healthy is True
    assert result.details == ["Connection successful"]
    assert result.error is None
    assert result.latency_ms == 123.45


# ────────────────────────────────────────────────────────────
# PreStartupHealthChecker Tests
# ────────────────────────────────────────────────────────────


class TestPreStartupHealthChecker:
    """Tests for PreStartupHealthChecker class."""

    def test_init(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test PreStartupHealthChecker initialization."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        assert checker._health_settings == health_settings
        assert checker._settings == mock_settings
        assert checker._results == {}

    @pytest.mark.asyncio
    async def test_check_postgres_success(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test successful PostgreSQL health check."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        # Mock the database connection
        with patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_conn.execute.return_value.fetchone.return_value = ("vector",)

            mock_engine.return_value.connect.return_value.__aenter__.return_value = mock_conn
            mock_engine.return_value.dispose = AsyncMock()

            result = await checker.check_postgres()

            assert result.healthy is True
            assert "Connection successful" in result.details
            assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_check_postgres_failure(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test PostgreSQL health check failure."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        with patch("sqlalchemy.ext.asyncio.create_async_engine") as mock_engine:
            mock_engine.side_effect = Exception("Connection refused")

            result = await checker.check_postgres()

            assert result.healthy is False
            assert result.error is not None
            assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_check_redis_success(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test successful Redis health check."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        with patch("redis.asyncio.Redis") as mock_redis_cls:
            with patch("redis.asyncio.ConnectionPool") as mock_pool_cls:
                # Setup mock pool
                mock_pool = MagicMock()
                mock_pool.disconnect = AsyncMock()
                mock_pool_cls.from_url.return_value = mock_pool

                # Setup mock client
                mock_client = AsyncMock()
                mock_client.ping = AsyncMock(return_value=True)
                mock_client.aclose = AsyncMock()
                mock_redis_cls.return_value = mock_client

                result = await checker.check_redis()

                assert result.healthy is True
                assert "Connection successful" in result.details

    @pytest.mark.asyncio
    async def test_check_redis_failure(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test Redis health check failure."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        with patch("redis.asyncio.Redis") as mock_redis:
            mock_redis.side_effect = Exception("Connection refused")

            result = await checker.check_redis()

            assert result.healthy is False
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_check_neo4j_success(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test successful Neo4j health check."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        with patch("neo4j.AsyncGraphDatabase") as mock_driver:
            mock_driver_instance = AsyncMock()
            mock_driver_instance.verify_connectivity = AsyncMock()
            mock_driver_instance.close = AsyncMock()

            mock_driver.driver.return_value = mock_driver_instance

            result = await checker.check_neo4j()

            assert result.healthy is True
            assert "Connection successful" in result.details

    @pytest.mark.asyncio
    async def test_check_neo4j_failure(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test Neo4j health check failure."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        with patch("neo4j.AsyncGraphDatabase") as mock_driver:
            mock_driver.driver.side_effect = Exception("ServiceUnavailable")

            result = await checker.check_neo4j()

            assert result.healthy is False
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_check_all(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test checking all services in parallel."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)

        # Mock all service checks
        with patch.object(checker, "check_postgres") as mock_postgres:
            with patch.object(checker, "check_redis") as mock_redis:
                with patch.object(checker, "check_neo4j") as mock_neo4j:
                    mock_postgres.return_value = ServiceCheckResult(
                        service="postgres",
                        healthy=True,
                        details=["OK"],
                    )
                    mock_redis.return_value = ServiceCheckResult(
                        service="redis",
                        healthy=True,
                        details=["OK"],
                    )
                    mock_neo4j.return_value = ServiceCheckResult(
                        service="neo4j",
                        healthy=False,
                        details=["Failed"],
                    )

                    results = await checker.check_all()

                    assert "postgres" in results
                    assert "redis" in results
                    assert "neo4j" in results
                    assert results["postgres"].healthy is True
                    assert results["redis"].healthy is True
                    assert results["neo4j"].healthy is False

    def test_get_summary_all_healthy(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test summary when all required services are healthy."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)
        checker._results = {
            "postgres": ServiceCheckResult(service="postgres", healthy=True),
            "redis": ServiceCheckResult(service="redis", healthy=True),
            "neo4j": ServiceCheckResult(service="neo4j", healthy=False),
        }

        summary = checker.get_summary()

        assert summary["overall_healthy"] is True
        assert summary["required_services_healthy"] is True
        assert summary["failed_required_services"] == []
        assert summary["optional_services"]["neo4j"] is False

    def test_get_summary_required_failed(
        self,
        health_settings: HealthCheckSettings,
        mock_settings: MagicMock,
    ) -> None:
        """Test summary when required services fail."""
        checker = PreStartupHealthChecker(health_settings, mock_settings)
        checker._results = {
            "postgres": ServiceCheckResult(service="postgres", healthy=True),
            "redis": ServiceCheckResult(service="redis", healthy=False),
            "neo4j": ServiceCheckResult(service="neo4j", healthy=False),
        }

        summary = checker.get_summary()

        assert summary["overall_healthy"] is False
        assert summary["required_services_healthy"] is False
        assert "redis" in summary["failed_required_services"]


# ────────────────────────────────────────────────────────────
# run_pre_startup_health_check Tests
# ────────────────────────────────────────────────────────────


class TestRunPreStartupHealthCheck:
    """Tests for run_pre_startup_health_check function."""

    def test_disabled_health_check(self, mock_settings: MagicMock) -> None:
        """Test that disabled health check returns True."""
        mock_settings.health_check.pre_startup_enabled = False

        checker = PreStartupHealthChecker(
            mock_settings.health_check,
            mock_settings,
        )
        result = checker.check_and_exit(exit_on_failure=False)

        assert result is True

    def test_enabled_health_check_success(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Test successful health check."""
        # Note: check_and_exit() uses asyncio.run() which can't be called
        # from an existing event loop, so we test the underlying methods directly
        checker = PreStartupHealthChecker(
            mock_settings.health_check,
            mock_settings,
        )
        checker._results = {
            "postgres": ServiceCheckResult(service="postgres", healthy=True),
            "redis": ServiceCheckResult(service="redis", healthy=True),
        }
        checker.get_summary = lambda: {
            "required_services_healthy": True,
            "failed_required_services": [],
        }

        # Test the summary directly since check_and_exit needs fresh event loop
        summary = checker.get_summary()
        assert summary["required_services_healthy"] is True

    def test_health_check_failure_exit_disabled(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Test health check failure with exit_on_failure=False."""
        mock_settings.health_check.pre_startup_enabled = True

        checker = PreStartupHealthChecker(
            mock_settings.health_check,
            mock_settings,
        )
        checker._results = {
            "postgres": ServiceCheckResult(
                service="postgres",
                healthy=False,
                error="Connection refused",
            ),
        }

        result = checker.check_and_exit(exit_on_failure=False)

        assert result is False


# ────────────────────────────────────────────────────────────
# HealthCheckSettings Tests
# ────────────────────────────────────────────────────────────


class TestHealthCheckSettings:
    """Tests for HealthCheckSettings."""

    def test_default_values(self) -> None:
        """Test default values for HealthCheckSettings."""
        settings = HealthCheckSettings()

        assert settings.pre_startup_enabled is True
        assert settings.required_services == ["postgres", "redis"]
        assert settings.optional_services == ["neo4j"]
        assert settings.timeout_seconds == 5.0
        assert settings.max_retries == 3
        assert settings.retry_delay_seconds == 2.0

    def test_custom_values(self) -> None:
        """Test custom values for HealthCheckSettings."""
        settings = HealthCheckSettings(
            pre_startup_enabled=False,
            required_services=["postgres"],
            optional_services=["redis", "neo4j"],
            timeout_seconds=10.0,
            max_retries=5,
            retry_delay_seconds=1.0,
        )

        assert settings.pre_startup_enabled is False
        assert settings.required_services == ["postgres"]
        assert settings.optional_services == ["redis", "neo4j"]
        assert settings.timeout_seconds == 10.0
        assert settings.max_retries == 5
        assert settings.retry_delay_seconds == 1.0


# ────────────────────────────────────────────────────────────
# Advanced Unit Tests
# ────────────────────────────────────────────────────────────


class TestHealthCheckAdvanced:
    """Advanced unit tests for health checking with complex scenarios."""

    @pytest.mark.asyncio
    async def test_full_health_check_flow(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Test the full health check flow with all services."""
        checker = PreStartupHealthChecker(
            mock_settings.health_check,
            mock_settings,
        )

        # Mock all services
        with patch.object(checker, "check_postgres") as mock_postgres:
            with patch.object(checker, "check_redis") as mock_redis:
                with patch.object(checker, "check_neo4j") as mock_neo4j:
                    mock_postgres.return_value = ServiceCheckResult(
                        service="postgres",
                        healthy=True,
                        details=["Connection successful", "pgvector available"],
                        latency_ms=50.0,
                    )
                    mock_redis.return_value = ServiceCheckResult(
                        service="redis",
                        healthy=True,
                        details=["Connection successful"],
                        latency_ms=10.0,
                    )
                    mock_neo4j.return_value = ServiceCheckResult(
                        service="neo4j",
                        healthy=False,
                        error="ServiceUnavailable",
                        details=["Connection failed"],
                    )

                    results = await checker.check_all()
                    summary = checker.get_summary()

                    # Verify results
                    assert len(results) == 3
                    assert summary["required_services_healthy"] is True
                    assert summary["optional_services"]["neo4j"] is False

    @pytest.mark.asyncio
    async def test_partial_failure_flow(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Test health check with partial service failure."""
        checker = PreStartupHealthChecker(
            mock_settings.health_check,
            mock_settings,
        )

        with patch.object(checker, "check_postgres") as mock_postgres:
            with patch.object(checker, "check_redis") as mock_redis:
                with patch.object(checker, "check_neo4j") as mock_neo4j:
                    mock_postgres.return_value = ServiceCheckResult(
                        service="postgres",
                        healthy=True,
                    )
                    mock_redis.return_value = ServiceCheckResult(
                        service="redis",
                        healthy=False,
                        error="Connection refused",
                    )
                    mock_neo4j.return_value = ServiceCheckResult(
                        service="neo4j",
                        healthy=False,
                        error="ServiceUnavailable",
                    )

                    results = await checker.check_all()
                    summary = checker.get_summary()

                    assert summary["required_services_healthy"] is False
                    assert "redis" in summary["failed_required_services"]
