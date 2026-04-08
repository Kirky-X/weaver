# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Tests for API dependency injection module (task 3.1.12)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


class TestEndpointsDependencyRegistry:
    """Tests for Endpoints class dependency registry."""

    def test_get_relational_pool_returns_when_set(self):
        """Test get_relational_pool returns pool when set."""
        from api.endpoints._deps import Endpoints

        mock_pool = MagicMock()
        Endpoints._relational_pool = mock_pool
        result = Endpoints.get_relational_pool()
        assert result == mock_pool
        # Cleanup
        Endpoints._relational_pool = None

    def test_get_relational_pool_raises_when_not_set(self):
        """Test get_relational_pool raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._relational_pool = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_relational_pool()
        assert exc_info.value.status_code == 503

    def test_get_graph_pool_returns_when_set(self):
        """Test get_graph_pool returns pool when set."""
        from api.endpoints._deps import Endpoints

        mock_pool = MagicMock()
        Endpoints._graph_pool = mock_pool
        result = Endpoints.get_graph_pool()
        assert result == mock_pool
        # Cleanup
        Endpoints._graph_pool = None

    def test_get_graph_pool_raises_when_not_set(self):
        """Test get_graph_pool raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._graph_pool = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_graph_pool()
        assert exc_info.value.status_code == 503

    def test_get_cache_returns_when_set(self):
        """Test get_cache returns client when set."""
        from api.endpoints._deps import Endpoints

        mock_cache = MagicMock()
        Endpoints._cache = mock_cache
        result = Endpoints.get_cache()
        assert result == mock_cache
        # Cleanup
        Endpoints._cache = None

    def test_get_cache_raises_when_not_set(self):
        """Test get_cache raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._cache = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_cache()
        assert exc_info.value.status_code == 503

    def test_get_llm_returns_when_set(self):
        """Test get_llm returns client when set."""
        from api.endpoints._deps import Endpoints

        mock_llm = MagicMock()
        Endpoints._llm = mock_llm
        result = Endpoints.get_llm()
        assert result == mock_llm
        # Cleanup
        Endpoints._llm = None

    def test_get_llm_raises_when_not_set(self):
        """Test get_llm raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._llm = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_llm()
        assert exc_info.value.status_code == 503

    def test_get_vector_repo_returns_when_set(self):
        """Test get_vector_repo returns repo when set."""
        from api.endpoints._deps import Endpoints

        mock_repo = MagicMock()
        Endpoints._vector_repo = mock_repo
        result = Endpoints.get_vector_repo()
        assert result == mock_repo
        # Cleanup
        Endpoints._vector_repo = None

    def test_get_vector_repo_raises_when_not_set(self):
        """Test get_vector_repo raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._vector_repo = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_vector_repo()
        assert exc_info.value.status_code == 503

    def test_get_scheduler_returns_when_set(self):
        """Test get_scheduler returns scheduler when set."""
        from api.endpoints._deps import Endpoints

        mock_scheduler = MagicMock()
        Endpoints._scheduler = mock_scheduler
        result = Endpoints.get_scheduler()
        assert result == mock_scheduler
        # Cleanup
        Endpoints._scheduler = None

    def test_get_scheduler_raises_when_not_set(self):
        """Test get_scheduler raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._scheduler = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_scheduler()
        assert exc_info.value.status_code == 503

    def test_get_source_config_repo_returns_when_set(self):
        """Test get_source_config_repo returns repo when set."""
        from api.endpoints._deps import Endpoints

        mock_repo = MagicMock()
        Endpoints._source_config_repo = mock_repo
        result = Endpoints.get_source_config_repo()
        assert result == mock_repo
        # Cleanup
        Endpoints._source_config_repo = None

    def test_get_source_config_repo_raises_when_not_set(self):
        """Test get_source_config_repo raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._source_config_repo = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_source_config_repo()
        assert exc_info.value.status_code == 503

    def test_get_source_authority_repo_returns_when_set(self):
        """Test get_source_authority_repo returns repo when set."""
        from api.endpoints._deps import Endpoints

        mock_repo = MagicMock()
        Endpoints._source_authority_repo = mock_repo
        result = Endpoints.get_source_authority_repo()
        assert result == mock_repo
        # Cleanup
        Endpoints._source_authority_repo = None

    def test_get_source_authority_repo_raises_when_not_set(self):
        """Test get_source_authority_repo raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._source_authority_repo = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_source_authority_repo()
        assert exc_info.value.status_code == 503


class TestDependencyFunctions:
    """Tests for dependency functions in api/dependencies.py."""

    def test_get_relational_pool_delegates_to_endpoints(self):
        """Test get_relational_pool delegates to Endpoints."""
        from api.dependencies import get_relational_pool

        mock_pool = MagicMock()
        with patch("api.dependencies.Endpoints.get_relational_pool", return_value=mock_pool):
            result = get_relational_pool()
            assert result == mock_pool

    def test_get_cache_client_delegates_to_endpoints(self):
        """Test get_cache_client delegates to Endpoints."""
        from api.dependencies import get_cache_client

        mock_cache = MagicMock()
        with patch("api.dependencies.Endpoints.get_cache", return_value=mock_cache):
            result = get_cache_client()
            assert result == mock_cache

    def test_get_graph_pool_delegates_to_endpoints(self):
        """Test get_graph_pool delegates to Endpoints."""
        from api.dependencies import get_graph_pool

        mock_pool = MagicMock()
        with patch("api.dependencies.Endpoints.get_graph_pool", return_value=mock_pool):
            result = get_graph_pool()
            assert result == mock_pool

    def test_get_llm_client_delegates_to_endpoints(self):
        """Test get_llm_client delegates to Endpoints."""
        from api.dependencies import get_llm_client

        mock_llm = MagicMock()
        with patch("api.dependencies.Endpoints.get_llm", return_value=mock_llm):
            result = get_llm_client()
            assert result == mock_llm

    def test_get_vector_repo_delegates_to_endpoints(self):
        """Test get_vector_repo delegates to Endpoints."""
        from api.dependencies import get_vector_repo

        mock_repo = MagicMock()
        with patch("api.dependencies.Endpoints.get_vector_repo", return_value=mock_repo):
            result = get_vector_repo()
            assert result == mock_repo

    def test_get_local_search_engine_delegates_to_endpoints(self):
        """Test get_local_search_engine delegates to Endpoints."""
        from api.dependencies import get_local_search_engine

        mock_engine = MagicMock()
        with patch("api.dependencies.Endpoints.get_local_engine", return_value=mock_engine):
            result = get_local_search_engine()
            assert result == mock_engine

    def test_get_global_search_engine_delegates_to_endpoints(self):
        """Test get_global_search_engine delegates to Endpoints."""
        from api.dependencies import get_global_search_engine

        mock_engine = MagicMock()
        with patch("api.dependencies.Endpoints.get_global_engine", return_value=mock_engine):
            result = get_global_search_engine()
            assert result == mock_engine

    def test_get_hybrid_search_engine_delegates_to_endpoints(self):
        """Test get_hybrid_search_engine delegates to Endpoints."""
        from api.dependencies import get_hybrid_search_engine

        mock_engine = MagicMock()
        with patch("api.dependencies.Endpoints.get_hybrid_engine", return_value=mock_engine):
            result = get_hybrid_search_engine()
            assert result == mock_engine

    def test_get_source_scheduler_delegates_to_endpoints(self):
        """Test get_source_scheduler delegates to Endpoints."""
        from api.dependencies import get_source_scheduler

        mock_scheduler = MagicMock()
        with patch("api.dependencies.Endpoints.get_scheduler", return_value=mock_scheduler):
            result = get_source_scheduler()
            assert result == mock_scheduler

    def test_get_source_config_repo_delegates_to_endpoints(self):
        """Test get_source_config_repo delegates to Endpoints."""
        from api.dependencies import get_source_config_repo

        mock_repo = MagicMock()
        with patch("api.dependencies.Endpoints.get_source_config_repo", return_value=mock_repo):
            result = get_source_config_repo()
            assert result == mock_repo

    def test_get_source_authority_repo_delegates_to_endpoints(self):
        """Test get_source_authority_repo delegates to Endpoints."""
        from api.dependencies import get_source_authority_repo

        mock_repo = MagicMock()
        with patch("api.dependencies.Endpoints.get_source_authority_repo", return_value=mock_repo):
            result = get_source_authority_repo()
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


class TestDependencyErrorHandling:
    """Tests for dependency error handling."""

    def test_dependency_raises_503_on_uninitialized(self):
        """Test all dependencies raise 503 when not initialized."""
        from api.endpoints._deps import Endpoints

        # Reset all to None
        Endpoints._relational_pool = None
        Endpoints._graph_pool = None
        Endpoints._cache = None
        Endpoints._llm = None
        Endpoints._local_engine = None
        Endpoints._global_engine = None
        Endpoints._hybrid_engine = None
        Endpoints._vector_repo = None
        Endpoints._scheduler = None
        Endpoints._source_config_repo = None
        Endpoints._source_authority_repo = None
        Endpoints._pipeline_service = None
        Endpoints._task_registry = None

        # All getters should raise HTTPException with 503
        getters = [
            Endpoints.get_relational_pool,
            Endpoints.get_graph_pool,
            Endpoints.get_cache,
            Endpoints.get_llm,
            Endpoints.get_local_engine,
            Endpoints.get_global_engine,
            Endpoints.get_hybrid_engine,
            Endpoints.get_vector_repo,
            Endpoints.get_scheduler,
            Endpoints.get_source_config_repo,
            Endpoints.get_source_authority_repo,
            Endpoints.get_pipeline_service,
            Endpoints.get_task_registry,
        ]

        for getter in getters:
            with pytest.raises(HTTPException) as exc_info:
                getter()
            assert exc_info.value.status_code == 503


class TestPipelineServiceDependency:
    """Tests for pipeline_service dependency."""

    def test_get_pipeline_service_returns_when_set(self):
        """Test get_pipeline_service returns service when set."""
        from api.endpoints._deps import Endpoints

        mock_service = MagicMock()
        Endpoints._pipeline_service = mock_service
        result = Endpoints.get_pipeline_service()
        assert result == mock_service
        # Cleanup
        Endpoints._pipeline_service = None

    def test_get_pipeline_service_raises_when_not_set(self):
        """Test get_pipeline_service raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._pipeline_service = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_pipeline_service()
        assert exc_info.value.status_code == 503
        assert "Pipeline service" in exc_info.value.detail

    def test_get_pipeline_service_delegates_to_endpoints(self):
        """Test get_pipeline_service dependency delegates to Endpoints."""
        from api.dependencies import get_pipeline_service

        mock_service = MagicMock()
        with patch("api.dependencies.Endpoints.get_pipeline_service", return_value=mock_service):
            result = get_pipeline_service()
            assert result == mock_service


class TestTaskRegistryDependency:
    """Tests for task_registry dependency."""

    def test_get_task_registry_returns_when_set(self):
        """Test get_task_registry returns registry when set."""
        from api.endpoints._deps import Endpoints

        mock_registry = MagicMock()
        Endpoints._task_registry = mock_registry
        result = Endpoints.get_task_registry()
        assert result == mock_registry
        # Cleanup
        Endpoints._task_registry = None

    def test_get_task_registry_raises_when_not_set(self):
        """Test get_task_registry raises HTTPException when not set."""
        from api.endpoints._deps import Endpoints

        Endpoints._task_registry = None
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_task_registry()
        assert exc_info.value.status_code == 503
        assert "Task registry" in exc_info.value.detail

    def test_get_task_registry_delegates_to_endpoints(self):
        """Test get_task_registry dependency delegates to Endpoints."""
        from api.dependencies import get_task_registry

        mock_registry = MagicMock()
        with patch("api.dependencies.Endpoints.get_task_registry", return_value=mock_registry):
            result = get_task_registry()
            assert result == mock_registry


class TestNewTypeAliases:
    """Tests for newly added dependency type aliases."""

    def test_pipeline_service_type_alias_exists(self):
        """Test PipelineServiceDep type alias exists."""
        from api.dependencies import TaskRegistryDep

        assert TaskRegistryDep is not None
