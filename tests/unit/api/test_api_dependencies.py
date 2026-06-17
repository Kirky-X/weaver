# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for API dependency injection module (task 3.1.12)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


class TestGetContainer:
    """Tests for get_container dependency."""

    def test_get_container_returns_container_when_initialized(self):
        """Test get_container returns container when initialized."""
        import container as container_module
        from api.dependencies import get_container

        mock_container = MagicMock()
        original = container_module._container
        container_module._container = mock_container
        try:
            result = get_container()
            assert result == mock_container
        finally:
            container_module._container = original

    def test_get_container_raises_503_when_not_initialized(self):
        """Test get_container raises HTTPException when not initialized."""
        import container as container_module
        from api.dependencies import get_container

        original = container_module._container
        container_module._container = None
        try:
            with pytest.raises(HTTPException) as exc_info:
                get_container()
            assert exc_info.value.status_code == 503
            assert "not initialized" in exc_info.value.detail.lower()
        finally:
            container_module._container = original


@pytest.mark.xdist_group(name="endpoints_deps")
class TestEndpointsDependencyRegistry:
    """Tests for Endpoints class dependency registry.

    The Endpoints class is a thin wrapper that delegates to
    api.dependencies.get_* functions, which in turn call container methods.
    Tests set up a mock container and verify the delegation chain.
    """

    @pytest.fixture(autouse=True)
    def cleanup_container(self):
        """Ensure container is cleared after each test for isolation."""
        yield
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()

    def _set_mock_container(self, **service_mocks):
        """Set up a mock container with the given service mocks.

        Each keyword argument sets up a container method that returns the
        mock. For example, _set_mock_container(relational_pool=mock_pool)
        makes container.relational_pool() return mock_pool.
        """
        import container as container_module

        mock_container = MagicMock()
        for method_name, return_value in service_mocks.items():
            getattr(mock_container, method_name).return_value = return_value
        container_module._container = mock_container
        return mock_container

    def test_get_relational_pool_returns_from_container(self):
        """Test get_relational_pool returns pool from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_pool = MagicMock()
        self._set_mock_container(relational_pool=mock_pool)
        result = Endpoints.get_relational_pool()
        assert result == mock_pool

    def test_get_relational_pool_raises_503_when_no_container(self):
        """Test get_relational_pool raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_relational_pool()
        assert exc_info.value.status_code == 503

    def test_get_graph_pool_returns_from_container(self):
        """Test get_graph_pool returns pool from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_pool = MagicMock()
        self._set_mock_container(graph_pool=mock_pool)
        result = Endpoints.get_graph_pool()
        assert result == mock_pool

    def test_get_graph_pool_raises_503_when_not_set(self):
        """Test get_graph_pool raises HTTPException when pool is None."""
        from api.endpoints.deps_registry import Endpoints

        self._set_mock_container(graph_pool=None)
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_graph_pool()
        assert exc_info.value.status_code == 503

    def test_get_cache_client_returns_from_container(self):
        """Test get_cache_client returns client from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_cache = MagicMock()
        self._set_mock_container(cache_client=mock_cache)
        result = Endpoints.get_cache_client()
        assert result == mock_cache

    def test_get_cache_client_raises_503_when_no_container(self):
        """Test get_cache_client raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_cache_client()
        assert exc_info.value.status_code == 503

    def test_get_llm_client_returns_from_container(self):
        """Test get_llm_client returns client from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_llm = MagicMock()
        mock_container = self._set_mock_container()
        mock_container.llm_client.return_value = mock_llm
        result = Endpoints.get_llm_client()
        assert result == mock_llm

    def test_get_llm_client_raises_503_when_not_set(self):
        """Test get_llm_client raises HTTPException when client is None."""
        from api.endpoints.deps_registry import Endpoints

        mock_container = self._set_mock_container()
        mock_container.llm_client.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_llm_client()
        assert exc_info.value.status_code == 503

    def test_get_vector_repo_returns_from_container(self):
        """Test get_vector_repo returns repo from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_repo = MagicMock()
        self._set_mock_container(vector_repo=mock_repo)
        result = Endpoints.get_vector_repo()
        assert result == mock_repo

    def test_get_vector_repo_raises_503_when_no_container(self):
        """Test get_vector_repo raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_vector_repo()
        assert exc_info.value.status_code == 503

    def test_get_source_scheduler_returns_from_container(self):
        """Test get_source_scheduler returns scheduler from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_scheduler = MagicMock()
        self._set_mock_container(source_scheduler=mock_scheduler)
        result = Endpoints.get_source_scheduler()
        assert result == mock_scheduler

    def test_get_source_scheduler_raises_503_when_no_container(self):
        """Test get_source_scheduler raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_source_scheduler()
        assert exc_info.value.status_code == 503

    def test_get_source_config_repo_returns_from_container(self):
        """Test get_source_config_repo returns repo from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_repo = MagicMock()
        self._set_mock_container(source_config_repo=mock_repo)
        result = Endpoints.get_source_config_repo()
        assert result == mock_repo

    def test_get_source_config_repo_raises_503_when_no_container(self):
        """Test get_source_config_repo raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_source_config_repo()
        assert exc_info.value.status_code == 503

    def test_get_source_authority_repo_returns_from_container(self):
        """Test get_source_authority_repo returns repo from container."""
        from api.endpoints.deps_registry import Endpoints

        mock_repo = MagicMock()
        self._set_mock_container(source_authority_repo=mock_repo)
        result = Endpoints.get_source_authority_repo()
        assert result == mock_repo

    def test_get_source_authority_repo_raises_503_when_no_container(self):
        """Test get_source_authority_repo raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_source_authority_repo()
        assert exc_info.value.status_code == 503


@pytest.mark.xdist_group(name="endpoints_deps")
class TestDependencyFunctions:
    """Tests for dependency functions in api/dependencies.py.

    These tests call the dependency functions directly with a mock container,
    bypassing FastAPI's Depends resolution.
    """

    def _make_mock_container(self):
        """Create a mock container with all service methods."""
        return MagicMock()

    def test_get_relational_pool_returns_from_container(self):
        """Test get_relational_pool returns pool from container."""
        from api.dependencies import get_relational_pool

        mock_container = self._make_mock_container()
        mock_pool = MagicMock()
        mock_container.relational_pool.return_value = mock_pool
        result = get_relational_pool(container=mock_container)
        assert result == mock_pool

    def test_get_cache_client_returns_from_container(self):
        """Test get_cache_client returns client from container."""
        from api.dependencies import get_cache_client

        mock_container = self._make_mock_container()
        mock_cache = MagicMock()
        mock_container.cache_client.return_value = mock_cache
        result = get_cache_client(container=mock_container)
        assert result == mock_cache

    def test_get_graph_pool_returns_from_container(self):
        """Test get_graph_pool returns pool from container."""
        from api.dependencies import get_graph_pool

        mock_container = self._make_mock_container()
        mock_pool = MagicMock()
        mock_container.graph_pool.return_value = mock_pool
        result = get_graph_pool(container=mock_container)
        assert result == mock_pool

    def test_get_llm_client_returns_from_container(self):
        """Test get_llm_client returns client from container."""
        from api.dependencies import get_llm_client

        mock_container = self._make_mock_container()
        mock_llm = MagicMock()
        mock_container.llm_client.return_value = mock_llm
        result = get_llm_client(container=mock_container)
        assert result == mock_llm

    def test_get_vector_repo_returns_from_container(self):
        """Test get_vector_repo returns repo from container."""
        from api.dependencies import get_vector_repo

        mock_container = self._make_mock_container()
        mock_repo = MagicMock()
        mock_container.vector_repo.return_value = mock_repo
        result = get_vector_repo(container=mock_container)
        assert result == mock_repo

    def test_get_local_search_engine_returns_from_container(self):
        """Test get_local_search_engine returns engine from container."""
        from api.dependencies import get_local_search_engine

        mock_container = self._make_mock_container()
        mock_engine = MagicMock()
        mock_container.local_search_engine.return_value = mock_engine
        result = get_local_search_engine(container=mock_container)
        assert result == mock_engine

    def test_get_global_search_engine_returns_from_container(self):
        """Test get_global_search_engine returns engine from container."""
        from api.dependencies import get_global_search_engine

        mock_container = self._make_mock_container()
        mock_engine = MagicMock()
        mock_container.global_search_engine.return_value = mock_engine
        result = get_global_search_engine(container=mock_container)
        assert result == mock_engine

    def test_get_hybrid_engine_returns_from_container(self):
        """Test get_hybrid_engine returns engine from container."""
        from api.dependencies import get_hybrid_engine

        mock_container = self._make_mock_container()
        mock_engine = MagicMock()
        mock_container.hybrid_search_engine.return_value = mock_engine
        result = get_hybrid_engine(container=mock_container)
        assert result == mock_engine

    def test_get_source_scheduler_returns_from_container(self):
        """Test get_source_scheduler returns scheduler from container."""
        from api.dependencies import get_source_scheduler

        mock_container = self._make_mock_container()
        mock_scheduler = MagicMock()
        mock_container.source_scheduler.return_value = mock_scheduler
        result = get_source_scheduler(container=mock_container)
        assert result == mock_scheduler

    def test_get_source_config_repo_returns_from_container(self):
        """Test get_source_config_repo returns repo from container."""
        from api.dependencies import get_source_config_repo

        mock_container = self._make_mock_container()
        mock_repo = MagicMock()
        mock_container.source_config_repo.return_value = mock_repo
        result = get_source_config_repo(container=mock_container)
        assert result == mock_repo

    def test_get_source_authority_repo_returns_from_container(self):
        """Test get_source_authority_repo returns repo from container."""
        from api.dependencies import get_source_authority_repo

        mock_container = self._make_mock_container()
        mock_repo = MagicMock()
        mock_container.source_authority_repo.return_value = mock_repo
        result = get_source_authority_repo(container=mock_container)
        assert result == mock_repo


class TestTypeAliases:
    """Tests for dependency type aliases."""

    def test_type_aliases_exist(self):
        """Test that all type aliases are defined."""
        from api.dependencies import (
            CachePoolDep,
            GlobalSearchEngineDep,
            GraphPoolDep,
            HybridSearchEngineDep,
            LLMClientDep,
            LocalSearchEngineDep,
            RelationalPoolDep,
            SourceAuthorityRepoDep,
            SourceConfigRepoDep,
            SourceSchedulerDep,
            VectorRepoDep,
        )

        # Type aliases should be Annotated types
        assert RelationalPoolDep is not None
        assert CachePoolDep is not None
        assert GraphPoolDep is not None
        assert LLMClientDep is not None
        assert VectorRepoDep is not None
        assert LocalSearchEngineDep is not None
        assert GlobalSearchEngineDep is not None
        assert HybridSearchEngineDep is not None
        assert SourceSchedulerDep is not None
        assert SourceConfigRepoDep is not None
        assert SourceAuthorityRepoDep is not None


@pytest.mark.xdist_group(name="endpoints_deps")
class TestDependencyErrorHandling:
    """Tests for dependency error handling.

    When no container is registered, all getters should raise HTTPException(503).
    """

    @pytest.fixture(autouse=True)
    def cleanup_container(self):
        """Ensure container is cleared after each test for isolation."""
        yield
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()

    def test_dependency_raises_503_on_uninitialized(self):
        """Test all Endpoints getters raise 503 when no container is set."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()

        # All getters should raise HTTPException with 503
        getters = [
            Endpoints.get_relational_pool,
            Endpoints.get_graph_pool,
            Endpoints.get_cache_client,
            Endpoints.get_llm_client,
            Endpoints.get_local_search_engine,
            Endpoints.get_global_search_engine,
            Endpoints.get_hybrid_engine,
            Endpoints.get_vector_repo,
            Endpoints.get_graph_repo,
            Endpoints.get_source_scheduler,
            Endpoints.get_source_config_repo,
            Endpoints.get_source_authority_repo,
            Endpoints.get_llm_failure_repo,
            Endpoints.get_llm_usage_repo,
            Endpoints.get_pipeline_service,
            Endpoints.get_task_registry,
        ]

        for getter in getters:
            with pytest.raises(HTTPException) as exc_info:
                getter()
            assert exc_info.value.status_code == 503


@pytest.mark.xdist_group(name="endpoints_deps")
class TestPipelineServiceDependency:
    """Tests for pipeline_service dependency."""

    @pytest.fixture(autouse=True)
    def cleanup_container(self):
        """Ensure container is cleared after each test for isolation."""
        yield
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()

    def test_get_pipeline_service_returns_from_container(self):
        """Test get_pipeline_service returns service from container."""
        import container as container_module
        from api.endpoints.deps_registry import Endpoints

        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_container.pipeline_service.return_value = mock_service
        container_module._container = mock_container

        result = Endpoints.get_pipeline_service()
        assert result == mock_service

    def test_get_pipeline_service_raises_503_when_no_container(self):
        """Test get_pipeline_service raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_pipeline_service()
        assert exc_info.value.status_code == 503
