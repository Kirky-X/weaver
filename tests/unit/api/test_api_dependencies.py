# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for API dependency injection module (task 3.1.12)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


class TestGetContainer:
    """Tests for get_container dependency."""

    def test_get_container_returns_container_when_initialized(self):
        """Test get_container returns container when initialized."""
        from api.dependencies import get_container
        from container import reset_container, set_container

        mock_container = MagicMock()
        set_container(mock_container)
        try:
            result = get_container()
            assert result == mock_container
        finally:
            reset_container()

    def test_get_container_raises_503_when_not_initialized(self):
        """Test get_container raises HTTPException when not initialized."""
        from api.dependencies import get_container
        from container import reset_container

        reset_container()
        with pytest.raises(HTTPException) as exc_info:
            get_container()
        assert exc_info.value.status_code == 503
        assert "not initialized" in exc_info.value.detail.lower()


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
        from container import set_container

        mock_container = MagicMock()
        for method_name, return_value in service_mocks.items():
            getattr(mock_container, method_name).return_value = return_value
        set_container(mock_container)
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
        from api.endpoints.deps_registry import Endpoints
        from container import set_container

        mock_service = MagicMock()
        mock_container = MagicMock()
        mock_container.pipeline_service.return_value = mock_service
        set_container(mock_container)

        result = Endpoints.get_pipeline_service()
        assert result == mock_service

    def test_get_pipeline_service_raises_503_when_no_container(self):
        """Test get_pipeline_service raises HTTPException when no container."""
        from api.endpoints.deps_registry import Endpoints

        Endpoints.reset()
        with pytest.raises(HTTPException) as exc_info:
            Endpoints.get_pipeline_service()
        assert exc_info.value.status_code == 503


# ── P0-4: API Dependencies 故障转移补全 (T025-T030) ────────────────────


@pytest.mark.xdist_group(name="endpoints_deps")
class TestMissingFailoverBranches:
    """Cover the 8 missing 503 branches in api/dependencies.py (R-api-deps-001).

    Each getter must raise HTTPException(503) when its container accessor
    returns None or raises RuntimeError. Previously these branches were
    uncovered, masking failover regressions.
    """

    def _make_container(self, **kwargs):
        """Build a MagicMock container with custom attribute behavior.

        Keyword args map to container attributes/methods. Values are set
        via MagicMock attribute assignment (works for both methods and
        plain attributes).
        """
        mock_container = MagicMock()
        for name, value in kwargs.items():
            if callable(value) or isinstance(value, Exception):
                # Set as method side_effect
                getattr(mock_container, name).side_effect = value
            else:
                # Set as method return value or attribute
                if name.startswith("_"):
                    setattr(mock_container, name, value)
                else:
                    getattr(mock_container, name).return_value = value
        return mock_container

    # ── 8 getters with 503 branches ───────────────────────────────

    def test_get_graph_pool_type_raises_503_when_pool_type_is_none(self):
        """get_graph_pool_type must raise 503 when container.graph_pool_type is None."""
        from api.dependencies import get_graph_pool_type

        mock_container = self._make_container(graph_pool_type=None)
        # graph_pool_type is a property/attribute, not a method; force it to None
        type(mock_container).graph_pool_type = property(lambda self: None)

        with pytest.raises(HTTPException) as exc_info:
            get_graph_pool_type(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "Graph pool type" in exc_info.value.detail

    def test_get_smart_fetcher_raises_503_on_runtime_error(self):
        """get_smart_fetcher must raise 503 when container.smart_fetcher raises RuntimeError."""
        from api.dependencies import get_smart_fetcher

        mock_container = self._make_container(smart_fetcher=RuntimeError("smart fetcher offline"))
        with pytest.raises(HTTPException) as exc_info:
            get_smart_fetcher(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "Smart fetcher" in exc_info.value.detail

    def test_get_llm_failure_repo_raises_503_on_runtime_error(self):
        """get_llm_failure_repo must raise 503 when container.llm_failure_repo raises."""
        from api.dependencies import get_llm_failure_repo

        mock_container = self._make_container(
            llm_failure_repo=RuntimeError("llm failure repo unavailable")
        )
        with pytest.raises(HTTPException) as exc_info:
            get_llm_failure_repo(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "LLM failure repo" in exc_info.value.detail

    def test_get_llm_usage_repo_raises_503_on_runtime_error(self):
        """get_llm_usage_repo must raise 503 when container.llm_usage_repo raises."""
        from api.dependencies import get_llm_usage_repo

        mock_container = self._make_container(
            llm_usage_repo=RuntimeError("llm usage repo unavailable")
        )
        with pytest.raises(HTTPException) as exc_info:
            get_llm_usage_repo(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "LLM usage repo" in exc_info.value.detail

    def test_get_saga_orchestrator_raises_503_on_runtime_error(self):
        """get_saga_orchestrator must raise 503 when container.saga_orchestrator raises."""
        from api.dependencies import get_saga_orchestrator

        mock_container = self._make_container(
            saga_orchestrator=RuntimeError("saga orchestrator unavailable")
        )
        with pytest.raises(HTTPException) as exc_info:
            get_saga_orchestrator(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "Saga orchestrator" in exc_info.value.detail

    def test_get_task_registry_raises_503_on_runtime_error(self):
        """get_task_registry must raise 503 when container.task_registry raises."""
        from api.dependencies import get_task_registry

        mock_container = self._make_container(
            task_registry=RuntimeError("task registry unavailable")
        )
        with pytest.raises(HTTPException) as exc_info:
            get_task_registry(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "Task registry" in exc_info.value.detail

    def test_get_embedding_service_raises_503_when_attr_is_none(self):
        """get_embedding_service must raise 503 when container._embedding_service is None."""
        from api.dependencies import get_embedding_service

        mock_container = MagicMock()
        mock_container._embedding_service = None
        with pytest.raises(HTTPException) as exc_info:
            get_embedding_service(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "Embedding service" in exc_info.value.detail

    def test_get_intent_classifier_raises_503_when_attr_is_none(self):
        """get_intent_classifier must raise 503 when container._intent_classifier is None."""
        from api.dependencies import get_intent_classifier

        mock_container = MagicMock()
        mock_container._intent_classifier = None
        with pytest.raises(HTTPException) as exc_info:
            get_intent_classifier(container=mock_container)
        assert exc_info.value.status_code == 503
        assert "Intent classifier" in exc_info.value.detail


@pytest.mark.xdist_group(name="endpoints_deps")
class TestOptionalGettersReturnNone:
    """Cover the 7 optional getter None paths + community_vector_repo branches (R-api-deps-002/003).

    Optional getters must return None (not raise) when their container
    accessor fails. This allows endpoints to gracefully degrade when
    optional services are unavailable.
    """

    def test_get_relational_pool_optional_returns_none_on_runtime_error(self):
        """get_relational_pool_optional returns None on RuntimeError (not raise)."""
        from api.dependencies import get_relational_pool_optional

        mock_container = MagicMock()
        mock_container.relational_pool.side_effect = RuntimeError("pool offline")
        result = get_relational_pool_optional(container=mock_container)
        assert result is None, f"Expected None on RuntimeError, got {type(result).__name__}"

    def test_get_graph_pool_optional_returns_none_when_pool_is_none(self):
        """get_graph_pool_optional returns None when container.graph_pool() returns None."""
        from api.dependencies import get_graph_pool_optional

        mock_container = MagicMock()
        mock_container.graph_pool.return_value = None
        result = get_graph_pool_optional(container=mock_container)
        assert result is None

    def test_get_cache_client_optional_returns_none_on_runtime_error(self):
        """get_cache_client_optional returns None on RuntimeError."""
        from api.dependencies import get_cache_client_optional

        mock_container = MagicMock()
        mock_container.cache_client.side_effect = RuntimeError("cache offline")
        result = get_cache_client_optional(container=mock_container)
        assert result is None

    def test_get_llm_client_optional_returns_none_when_client_is_none(self):
        """get_llm_client_optional returns None when container.llm_client() returns None."""
        from api.dependencies import get_llm_client_optional

        mock_container = MagicMock()
        mock_container.llm_client.return_value = None
        result = get_llm_client_optional(container=mock_container)
        assert result is None

    def test_get_embedding_service_optional_returns_none_when_attr_missing(self):
        """get_embedding_service_optional returns None when _embedding_service attr missing."""
        from api.dependencies import get_embedding_service_optional

        mock_container = MagicMock()
        # MagicMock auto-creates attributes; delete to simulate missing
        if hasattr(mock_container, "_embedding_service"):
            del mock_container._embedding_service
        # Spec-based mock that doesn't auto-create attributes
        mock_container = MagicMock(spec=[])
        result = get_embedding_service_optional(container=mock_container)
        assert result is None

    def test_get_intent_classifier_optional_returns_none_when_attr_missing(self):
        """get_intent_classifier_optional returns None when _intent_classifier attr missing."""
        from api.dependencies import get_intent_classifier_optional

        mock_container = MagicMock(spec=[])
        result = get_intent_classifier_optional(container=mock_container)
        assert result is None

    def test_get_community_vector_repo_returns_none_for_duckdb_backend(self):
        """get_community_vector_repo returns None when relational_pool_type != 'postgres'."""
        from api.dependencies import get_community_vector_repo

        mock_container = MagicMock()
        # DuckDB backend — community_vectors is PG-only
        type(mock_container).relational_pool_type = property(lambda self: "duckdb")
        result = get_community_vector_repo(container=mock_container)
        assert result is None, f"DuckDB backend should return None, got {type(result).__name__}"

    def test_get_community_vector_repo_returns_instance_for_postgres_backend(self):
        """get_community_vector_repo returns CommunityVectorRepo instance for PG backend."""
        from unittest.mock import patch

        from api.dependencies import get_community_vector_repo

        mock_container = MagicMock()
        type(mock_container).relational_pool_type = property(lambda self: "postgres")

        mock_pool = MagicMock()
        mock_container.relational_pool.return_value = mock_pool

        mock_qb = MagicMock()
        mock_repo = MagicMock()

        with (
            patch(
                "core.db.query_builders.create_vector_query_builder",
                return_value=mock_qb,
            ) as mock_create_qb,
            patch(
                "modules.storage.postgres.community_vector_repo.CommunityVectorRepo",
                return_value=mock_repo,
            ) as mock_repo_cls,
        ):
            result = get_community_vector_repo(container=mock_container)

        assert result is mock_repo, "Expected CommunityVectorRepo instance for PG backend"
        mock_create_qb.assert_called_once_with("postgres")
        mock_repo_cls.assert_called_once_with(pool=mock_pool, query_builder=mock_qb)


@pytest.mark.xdist_group(name="endpoints_deps")
class TestTypeFallbackGetters:
    """Cover the 3 type-fallback getters (R-api-deps-004).

    These getters return a type string with graceful fallbacks:
      - get_relational_type: 'postgres' | 'duckdb' | 'unknown'
      - get_graph_type: 'neo4j' | 'ladybug' | 'unknown'
      - get_cache_type: 'redis' | 'cashews' | <class_name> | 'none'
    """

    def test_get_relational_type_returns_unknown_on_runtime_error(self):
        """get_relational_type returns 'unknown' when pool_type accessor raises."""
        from api.dependencies import get_relational_type

        mock_container = MagicMock()
        type(mock_container).relational_pool_type = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("unavailable"))
        )
        result = get_relational_type(container=mock_container)
        assert result == "unknown", f"Expected 'unknown' on RuntimeError, got '{result}'"

    def test_get_graph_type_returns_unknown_when_pool_type_is_none(self):
        """get_graph_type returns 'unknown' when graph_pool_type is None."""
        from api.dependencies import get_graph_type

        mock_container = MagicMock()
        type(mock_container).graph_pool_type = property(lambda self: None)
        result = get_graph_type(container=mock_container)
        assert result == "unknown", f"Expected 'unknown' for None pool_type, got '{result}'"

    def test_get_cache_type_returns_none_on_runtime_error(self):
        """get_cache_type returns 'none' when cache_client() raises RuntimeError."""
        from api.dependencies import get_cache_type

        mock_container = MagicMock()
        mock_container.cache_client.side_effect = RuntimeError("cache offline")
        result = get_cache_type(container=mock_container)
        assert result == "none", f"Expected 'none' on RuntimeError, got '{result}'"

    def test_get_cache_type_returns_cache_type_attr_when_present(self):
        """get_cache_type returns cache.cache_type when the attribute exists (e.g. 'redis')."""
        from api.dependencies import get_cache_type

        mock_container = MagicMock()
        mock_cache = MagicMock()
        mock_cache.cache_type = "redis"
        mock_container.cache_client.return_value = mock_cache

        result = get_cache_type(container=mock_container)
        assert result == "redis", f"Expected 'redis', got '{result}'"

    def test_get_cache_type_returns_class_name_when_attr_missing(self):
        """get_cache_type returns type(cache).__name__ when cache_type attribute is missing."""
        from api.dependencies import get_cache_type

        mock_container = MagicMock()
        # Use a spec-restricted mock that lacks cache_type attribute
        mock_cache = MagicMock(spec=["ping"])  # only 'ping' method, no cache_type
        mock_container.cache_client.return_value = mock_cache

        result = get_cache_type(container=mock_container)
        assert result == type(mock_cache).__name__, (
            f"Expected class name '{type(mock_cache).__name__}', got '{result}'"
        )


@pytest.mark.xdist_group(name="endpoints_deps")
class TestRemainingFailoverBranches:
    """Cover the remaining 503 branches to push api/dependencies.py coverage above 95%.

    These branches mirror TestDependencyErrorHandling but test api.dependencies
    functions directly (bypassing the Endpoints wrapper) to ensure each getter
    raises HTTPException(503) on RuntimeError.
    """

    @pytest.mark.parametrize(
        "import_name,container_method,detail_substring",
        [
            ("get_relational_pool", "relational_pool", "Relational pool"),
            ("get_cache_client", "cache_client", "Cache pool"),
            ("get_vector_repo", "vector_repo", "Vector store"),
            ("get_graph_repo", "graph_repo", "Graph repository"),
            ("get_source_scheduler", "source_scheduler", "Source scheduler"),
            ("get_source_config_repo", "source_config_repo", "Source config repository"),
            ("get_source_authority_repo", "source_authority_repo", "Source authority repo"),
            ("get_pipeline_service", "pipeline_service", "Pipeline service"),
        ],
    )
    def test_getter_raises_503_on_runtime_error(
        self, import_name, container_method, detail_substring
    ):
        """Each getter must raise HTTPException(503) on RuntimeError from container."""
        import api.dependencies as deps

        getter = getattr(deps, import_name)
        mock_container = MagicMock()
        getattr(mock_container, container_method).side_effect = RuntimeError("offline")

        with pytest.raises(HTTPException) as exc_info:
            getter(container=mock_container)
        assert exc_info.value.status_code == 503
        assert detail_substring in exc_info.value.detail, (
            f"Expected '{detail_substring}' in detail, got '{exc_info.value.detail}'"
        )

    @pytest.mark.parametrize(
        "import_name,container_method,detail_substring",
        [
            ("get_local_search_engine", "local_search_engine", "Search service"),
            ("get_global_search_engine", "global_search_engine", "Search service"),
            ("get_hybrid_engine", "hybrid_search_engine", "Hybrid search service"),
        ],
    )
    def test_search_engine_getter_raises_503_when_engine_is_none(
        self, import_name, container_method, detail_substring
    ):
        """Each search engine getter must raise 503 when container returns None."""
        import api.dependencies as deps

        getter = getattr(deps, import_name)
        mock_container = MagicMock()
        getattr(mock_container, container_method).return_value = None

        with pytest.raises(HTTPException) as exc_info:
            getter(container=mock_container)
        assert exc_info.value.status_code == 503
        assert detail_substring in exc_info.value.detail

    def test_get_graph_pool_type_returns_pool_type_when_set(self):
        """get_graph_pool_type happy path: returns the pool type string."""
        from api.dependencies import get_graph_pool_type

        mock_container = MagicMock()
        type(mock_container).graph_pool_type = property(lambda self: "neo4j")
        result = get_graph_pool_type(container=mock_container)
        assert result == "neo4j"

    def test_get_embedding_service_returns_service_when_set(self):
        """get_embedding_service happy path: returns the service instance."""
        from api.dependencies import get_embedding_service

        mock_container = MagicMock()
        mock_service = MagicMock()
        mock_container._embedding_service = mock_service
        result = get_embedding_service(container=mock_container)
        assert result is mock_service

    def test_get_intent_classifier_returns_classifier_when_set(self):
        """get_intent_classifier happy path: returns the classifier instance."""
        from api.dependencies import get_intent_classifier

        mock_container = MagicMock()
        mock_classifier = MagicMock()
        mock_container._intent_classifier = mock_classifier
        result = get_intent_classifier(container=mock_container)
        assert result is mock_classifier

    def test_get_community_vector_repo_returns_none_on_runtime_error(self):
        """get_community_vector_repo returns None on RuntimeError (not raise)."""
        from api.dependencies import get_community_vector_repo

        mock_container = MagicMock()
        # relational_pool_type raises RuntimeError → caught → returns None
        type(mock_container).relational_pool_type = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("pool unavailable"))
        )
        result = get_community_vector_repo(container=mock_container)
        assert result is None
