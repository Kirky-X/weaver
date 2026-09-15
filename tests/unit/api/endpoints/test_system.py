# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for system endpoints (system.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.schemas.response import APIResponse
from core.exceptions import BusinessError


# ── Helpers ────────────────────────────────────────────────────────


def _mock_container(
    *,
    llm_client: object | None = None,
    search_engine: object | None = None,
    graph_pool: object | None = None,
    relational_pool: object | None = None,
    cache_client: object | None = None,
):
    """Build a mock container with configurable components."""
    container = MagicMock()
    container._llm_client = llm_client
    container._local_search_engine = search_engine
    container.graph_pool.return_value = graph_pool
    container.relational_pool.return_value = relational_pool
    container.cache_client.return_value = cache_client
    container.relational_pool_type = "postgres"
    container.graph_pool_type = "neo4j"
    return container


# ── /status ────────────────────────────────────────────────────────


class TestSystemStatus:
    """Tests for GET /api/v1/status."""

    @pytest.mark.asyncio
    async def test_returns_running_status(self):
        """system_status returns running status with db types."""
        from api.endpoints.system import system_status

        result = await system_status(
            _="env-key",
            relational_type="postgres",
            graph_type="neo4j",
            cache_type="redis",
        )

        assert isinstance(result, APIResponse)
        data = result.data
        assert data["status"] == "running"
        assert data["database"]["relational"] == "postgres"
        assert data["database"]["graph"] == "neo4j"
        assert data["database"]["cache"] == "redis"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_version_from_pyproject(self):
        """system_status reads version from pyproject.toml."""
        from api.endpoints.system import system_status

        result = await system_status(
            _="env-key",
            relational_type="duckdb",
            graph_type="ladybug",
            cache_type="fallback",
        )

        # version should be a string (may be "unknown" if pyproject unreadable)
        assert isinstance(result.data["version"], str)

    @pytest.mark.asyncio
    async def test_version_fallback_on_read_error(self):
        """system_status returns 'unknown' when pyproject.toml is unreadable."""
        from api.endpoints.system import _read_app_version, system_status

        # _read_app_version is lru_cache'd (process-stable); clear before and
        # after so the mocked open() is actually exercised and the "unknown"
        # fallback does not leak into other tests in this process.
        with patch("builtins.open", side_effect=OSError("not found")):
            _read_app_version.cache_clear()
            try:
                result = await system_status(
                    _="env-key",
                    relational_type="duckdb",
                    graph_type="ladybug",
                    cache_type="fallback",
                )
            finally:
                _read_app_version.cache_clear()

        assert result.data["version"] == "unknown"


# ── /config ────────────────────────────────────────────────────────


class TestSystemConfig:
    """Tests for GET /api/v1/config."""

    @pytest.mark.asyncio
    async def test_returns_config_with_container(self):
        """system_config returns configuration from container."""
        from api.endpoints.system import system_config

        mock_container = _mock_container(
            llm_client=MagicMock(),
            search_engine=MagicMock(),
            graph_pool=MagicMock(),
        )

        with patch("container.get_container", return_value=mock_container):
            result = await system_config(
                _="admin",
                relational_type="postgres",
                graph_type="neo4j",
            )

        data = result.data
        assert data["relational_pool_type"] == "postgres"
        assert data["graph_pool_type"] == "neo4j"
        assert data["llm_enabled"] is True
        assert data["search_enabled"] is True
        assert data["graph_available"] is True

    @pytest.mark.asyncio
    async def test_returns_config_without_container(self):
        """system_config returns safe defaults when container unavailable."""
        from api.endpoints.system import system_config

        with patch("container.get_container", side_effect=RuntimeError("not started")):
            result = await system_config(
                _="admin",
                relational_type="duckdb",
                graph_type="ladybug",
            )

        data = result.data
        assert data["llm_enabled"] is False
        assert data["search_enabled"] is False
        assert data["graph_available"] is False

    @pytest.mark.asyncio
    async def test_graph_unavailable_when_pool_none(self):
        """graph_available is False when graph_pool returns None."""
        from api.endpoints.system import system_config

        mock_container = _mock_container(graph_pool=None)

        with patch("container.get_container", return_value=mock_container):
            result = await system_config(
                _="admin",
                relational_type="postgres",
                graph_type="neo4j",
            )

        assert result.data["graph_available"] is False


# ── /health/dependencies ──────────────────────────────────────────


class TestHealthDependencies:
    """Tests for GET /api/v1/health/dependencies."""

    @pytest.mark.asyncio
    async def test_all_healthy(self):
        """All dependencies report ok when connections succeed."""
        from api.endpoints.system import health_dependencies

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.session_context.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_pool.session_context.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_gpool = MagicMock()
        mock_gpool.execute_query = AsyncMock()

        mock_cache = MagicMock()
        mock_cache.cache_type = "redis"
        mock_cache.ping = AsyncMock()

        mock_llm = MagicMock()
        mock_llm._providers = {"openai": MagicMock(), "anthropic": MagicMock()}

        mock_container = MagicMock()
        mock_container.relational_pool.return_value = mock_pool
        mock_container.relational_pool_type = "postgres"
        mock_container.graph_pool.return_value = mock_gpool
        mock_container.graph_pool_type = "neo4j"
        mock_container.cache_client.return_value = mock_cache
        mock_container.llm_client.return_value = mock_llm

        with patch("container.get_container", return_value=mock_container):
            result = await health_dependencies(_="admin")

        data = result.data
        assert data["status"] == "healthy"
        assert data["dependencies"]["relational"]["status"] == "ok"
        assert data["dependencies"]["graph"]["status"] == "ok"
        assert data["dependencies"]["cache"]["status"] == "ok"
        assert data["dependencies"]["llm"]["status"] == "ok"
        assert data["dependencies"]["llm"]["provider_count"] == 2

    @pytest.mark.asyncio
    async def test_degraded_when_relational_down(self):
        """Status is degraded when relational DB fails."""
        from api.endpoints.system import health_dependencies

        mock_pool = MagicMock()
        mock_pool.session_context.return_value.__aenter__ = AsyncMock(
            side_effect=ConnectionError("refused")
        )
        mock_pool.session_context.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_gpool = MagicMock()
        mock_gpool.execute_query = AsyncMock()

        mock_cache = MagicMock()
        mock_cache.cache_type = "redis"
        mock_cache.ping = AsyncMock()

        mock_llm = MagicMock()
        mock_llm._providers = {}

        mock_container = MagicMock()
        mock_container.relational_pool.return_value = mock_pool
        mock_container.relational_pool_type = "postgres"
        mock_container.graph_pool.return_value = mock_gpool
        mock_container.graph_pool_type = "neo4j"
        mock_container.cache_client.return_value = mock_cache
        mock_container.llm_client.return_value = mock_llm

        with patch("container.get_container", return_value=mock_container):
            result = await health_dependencies(_="admin")

        data = result.data
        assert data["status"] == "degraded"
        assert data["dependencies"]["relational"]["status"] == "error"
        assert data["dependencies"]["relational"]["error_type"] == "ConnectionError"

    @pytest.mark.asyncio
    async def test_container_not_available(self):
        """Returns degraded when container is not initialized."""
        from api.endpoints.system import health_dependencies

        with patch("container.get_container", side_effect=RuntimeError("not started")):
            result = await health_dependencies(_="admin")

        # container=None must be flagged as an error so the endpoint
        # reports degraded instead of "healthy" over an empty details dict.
        data = result.data
        assert data["status"] == "degraded"
        assert data["dependencies"]["container"]["status"] == "error"


# ── /admin/cache/clear ────────────────────────────────────────────


class TestClearCache:
    """Tests for POST /api/v1/admin/cache/clear."""

    @pytest.mark.asyncio
    async def test_clear_cache_success(self):
        """Clear cache scans and deletes matching keys."""
        from api.endpoints.system import clear_cache

        mock_cache = MagicMock()

        async def mock_scan_iter(pattern="*", count=500):
            for key in ["key1", "key2", "key3"]:
                yield key

        mock_cache.scan_iter = mock_scan_iter
        mock_cache.delete = AsyncMock(side_effect=lambda *keys: len(keys))

        result = await clear_cache(pattern="test:*", _="admin", cache_client=mock_cache)

        data = result.data
        assert data["deleted"] == 3
        assert data["pattern"] == "test:*"
        assert data["status"] == "completed"
        #: one batched variadic delete instead of N single-key calls
        mock_cache.delete.assert_awaited_once_with("key1", "key2", "key3")

    @pytest.mark.asyncio
    async def test_clear_cache_raises_when_no_cache(self):
        """Raises 503 when cache client is None."""
        from api.endpoints.system import clear_cache

        with pytest.raises(Exception) as exc_info:
            await clear_cache(pattern="*", _="admin", cache_client=None)

    @pytest.mark.asyncio
    async def test_clear_cache_default_pattern(self):
        """Default pattern '*' clears all keys."""
        from api.endpoints.system import clear_cache

        mock_cache = MagicMock()

        async def mock_scan_iter(pattern="*", count=500):
            yield "only_key"

        mock_cache.scan_iter = mock_scan_iter
        mock_cache.delete = AsyncMock(return_value=1)

        result = await clear_cache(pattern="*", _="admin", cache_client=mock_cache)

        assert result.data["deleted"] == 1


# ── /admin/config/reload ──────────────────────────────────────────


class TestReloadConfig:
    """Tests for POST /api/v1/admin/config/reload."""

    @pytest.mark.asyncio
    async def test_reload_success(self):
        """Successful reload returns provider count."""
        from api.endpoints.system import reload_config

        mock_settings = MagicMock()
        mock_settings.providers = {"openai": MagicMock()}

        mock_live_config = MagicMock()
        mock_live_config.reload.return_value = mock_settings
        mock_live_config._config_path = "config/llm.toml"

        mock_container = MagicMock()
        mock_container._live_config = mock_live_config

        with patch("container.get_container", return_value=mock_container):
            result = await reload_config(_="admin")

        data = result.data
        assert data["status"] == "reloaded"
        assert data["providers"] == 1

    @pytest.mark.asyncio
    async def test_reload_container_not_initialized(self):
        """Raises 503 when container is not initialized."""
        from api.endpoints.system import reload_config

        with patch("container.get_container", side_effect=RuntimeError("not started")):
            with pytest.raises(HTTPException):
                await reload_config(_="admin")

    @pytest.mark.asyncio
    async def test_reload_live_config_not_initialized(self):
        """Raises 503 when live config is not initialized."""
        from api.endpoints.system import reload_config

        mock_container = MagicMock()
        mock_container._live_config = None

        with patch("container.get_container", return_value=mock_container):
            with pytest.raises(HTTPException):
                await reload_config(_="admin")

    @pytest.mark.asyncio
    async def test_reload_failure_returns_500(self):
        """Raises 500 when reload raises."""
        from api.endpoints.system import reload_config

        mock_live_config = MagicMock()
        mock_live_config.reload.side_effect = ValueError("bad config")

        mock_container = MagicMock()
        mock_container._live_config = mock_live_config

        with patch("container.get_container", return_value=mock_container):
            with pytest.raises(HTTPException):
                await reload_config(_="admin")


# ── health_endpoint ───────────────────────────────────────────────


class TestHealthEndpoint:
    """Tests for the unauthenticated health endpoint."""

    @pytest.mark.asyncio
    async def test_returns_only_overall_status(self):
        """Health endpoint exposes only overall status (CWE-200 fix)."""
        from api.endpoints.system import health_endpoint

        mock_result = MagicMock()
        mock_result.status = "healthy"

        with patch(
            "api.endpoints.system.health_check", new_callable=AsyncMock, return_value=mock_result
        ):
            result = await health_endpoint()

        data = result.data
        assert data["status"] == "healthy"
        # Must NOT expose per-dependency details
        assert "checks" not in data


# ── metrics_endpoint ──────────────────────────────────────────────


class TestMetricsEndpoint:
    """Tests for the Prometheus metrics endpoint."""

    @pytest.mark.asyncio
    async def test_returns_prometheus_metrics(self):
        """Metrics endpoint returns PlainTextResponse with prometheus content."""
        from api.endpoints.system import metrics_endpoint

        with patch("api.endpoints.system.generate_latest", return_value=b"# HELP test\n"):
            result = await metrics_endpoint(_=None)

        assert b"# HELP test" in result.body
