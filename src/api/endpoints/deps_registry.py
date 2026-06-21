# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Centralized dependency registry for API endpoints (transitional thin wrapper).

This module retains the ``Endpoints`` class as a backward-compatibility wrapper
around :mod:`api.dependencies`. All ``get_*`` methods delegate to the
corresponding FastAPI dependency functions in :mod:`api.dependencies`.

New code should depend on :mod:`api.dependencies` directly via FastAPI's
``Depends()`` pattern instead of using ``Endpoints.get_*()``.

All getters return Protocol types, not concrete implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.observability import get_logger

if TYPE_CHECKING:
    from container import Container
    from core.llm import LLMClient
    from core.protocols import (
        CachePool,
        EmbeddingServiceProtocol,
        GraphPool,
        RelationalPool,
        VectorRepository,
    )
    from core.saga import SagaOrchestrator
    from core.services.pipeline_service import PipelineServiceImpl
    from core.services.task_registry import InMemoryTaskRegistry
    from modules.analytics import LLMFailureRepo, LLMUsageRepo
    from modules.ingestion import SourceConfigRepo, SourceScheduler
    from modules.knowledge.search import (
        GlobalSearchEngine,
        HybridSearchEngine,
        LocalSearchEngine,
    )
    from modules.storage import SourceAuthorityRepo
    from modules.storage.graph_repo import GraphRepository

log = get_logger(__name__)


class Endpoints:
    """Transitional thin wrapper around :mod:`api.dependencies`.

    All ``get_*`` static methods delegate to the corresponding FastAPI
    dependency functions in :mod:`api.dependencies`. This class exists
    solely for backward compatibility during the migration period.

    New code MUST use ``from api.dependencies import get_*`` with FastAPI's
    ``Depends()`` pattern instead of ``Endpoints.get_*()``.

    All types are Protocol types, enabling database abstraction.
    """

    @staticmethod
    def _container() -> Container:
        """Get the current container for direct (non-FastAPI) calls.

        Uses :func:`api.dependencies.get_container` so that the same
        error handling (HTTPException 503) applies when no container
        is registered.
        """
        from api.dependencies import get_container

        return get_container()

    # ── Relational Pool ───────────────────────────────────────────────

    @staticmethod
    def get_relational_pool() -> RelationalPool:
        """Get relational database pool (PostgreSQL or DuckDB)."""
        from api.dependencies import get_relational_pool

        return get_relational_pool(container=Endpoints._container())

    # ── Graph Pool ────────────────────────────────────────────────────

    @staticmethod
    def get_graph_pool() -> GraphPool:
        """Get graph database pool (Neo4j or LadybugDB)."""
        from api.dependencies import get_graph_pool

        return get_graph_pool(container=Endpoints._container())

    @staticmethod
    def get_graph_pool_type() -> str:
        """Get graph database type ('neo4j' or 'ladybug')."""
        from api.dependencies import get_graph_pool_type

        return get_graph_pool_type(container=Endpoints._container())

    @staticmethod
    def get_relational_type() -> str:
        """Get relational database type ('postgres' or 'duckdb')."""
        from api.dependencies import get_relational_type

        return get_relational_type(container=Endpoints._container())

    @staticmethod
    def get_graph_type() -> str:
        """Get graph database type ('neo4j' or 'ladybug')."""
        from api.dependencies import get_graph_type

        return get_graph_type(container=Endpoints._container())

    @staticmethod
    def get_cache_type() -> str:
        """Get cache type ('redis' or 'cashews')."""
        from api.dependencies import get_cache_type

        return get_cache_type(container=Endpoints._container())

    # ── Cache ─────────────────────────────────────────────────────────

    @staticmethod
    def get_cache_client() -> CachePool:
        """Get cache pool (Redis or in-memory fallback)."""
        from api.dependencies import get_cache_client

        return get_cache_client(container=Endpoints._container())

    # ── LLM ───────────────────────────────────────────────────────────

    @staticmethod
    def get_llm_client() -> LLMClient:
        """Get LLM client."""
        from api.dependencies import get_llm_client

        return get_llm_client(container=Endpoints._container())

    @staticmethod
    def get_llm_client_optional() -> LLMClient | None:
        """Get LLM client or None if unavailable."""
        from api.dependencies import get_llm_client_optional

        return get_llm_client_optional(container=Endpoints._container())

    # ── Search Engines ────────────────────────────────────────────────

    @staticmethod
    def get_local_search_engine() -> LocalSearchEngine:
        """Get local search engine."""
        from api.dependencies import get_local_search_engine

        return get_local_search_engine(container=Endpoints._container())

    @staticmethod
    def get_global_search_engine() -> GlobalSearchEngine:
        """Get global search engine."""
        from api.dependencies import get_global_search_engine

        return get_global_search_engine(container=Endpoints._container())

    @staticmethod
    def get_hybrid_engine() -> HybridSearchEngine:
        """Get hybrid search engine."""
        from api.dependencies import get_hybrid_engine

        return get_hybrid_engine(container=Endpoints._container())

    # ── Repositories ──────────────────────────────────────────────────

    @staticmethod
    def get_vector_repo() -> VectorRepository:
        """Get vector repository."""
        from api.dependencies import get_vector_repo

        return get_vector_repo(container=Endpoints._container())

    @staticmethod
    def get_graph_repo() -> GraphRepository:
        """Get graph repository with database-agnostic query builder."""
        from api.dependencies import get_graph_repo

        return get_graph_repo(container=Endpoints._container())

    # ── Scheduler ──────────────────────────────────────────────────────

    @staticmethod
    def get_source_scheduler() -> SourceScheduler:
        """Get source scheduler."""
        from api.dependencies import get_source_scheduler

        return get_source_scheduler(container=Endpoints._container())

    # ── Config Repos ──────────────────────────────────────────────────

    @staticmethod
    def get_source_config_repo() -> SourceConfigRepo:
        """Get source config repository."""
        from api.dependencies import get_source_config_repo

        return get_source_config_repo(container=Endpoints._container())

    @staticmethod
    def get_source_authority_repo() -> SourceAuthorityRepo:
        """Get source authority repository."""
        from api.dependencies import get_source_authority_repo

        return get_source_authority_repo(container=Endpoints._container())

    @staticmethod
    def get_llm_failure_repo() -> LLMFailureRepo:
        """Get LLM failure repository."""
        from api.dependencies import get_llm_failure_repo

        return get_llm_failure_repo(container=Endpoints._container())

    @staticmethod
    def get_llm_usage_repo() -> LLMUsageRepo:
        """Get LLM usage repository."""
        from api.dependencies import get_llm_usage_repo

        return get_llm_usage_repo(container=Endpoints._container())

    # ── Pipeline Service ───────────────────────────────────────────────

    @staticmethod
    def get_pipeline_service() -> PipelineServiceImpl:
        """Get the pipeline service."""
        from api.dependencies import get_pipeline_service

        return get_pipeline_service(container=Endpoints._container())

    # ── Task Registry ──────────────────────────────────────────────────

    @staticmethod
    def get_task_registry() -> InMemoryTaskRegistry:
        """Get the task registry for background task tracking."""
        from api.dependencies import get_task_registry

        return get_task_registry(container=Endpoints._container())

    # ── Saga Orchestrator ──────────────────────────────────────────────

    @staticmethod
    def get_saga_orchestrator() -> SagaOrchestrator:
        """Get the Saga orchestrator for cross-database transaction coordination."""
        from api.dependencies import get_saga_orchestrator

        return get_saga_orchestrator(container=Endpoints._container())

    # ── Embedding & Intent Services ────────────────────────────────────

    @staticmethod
    def get_embedding_service() -> EmbeddingServiceProtocol:
        """Get embedding service for search endpoints."""
        from api.dependencies import get_embedding_service

        return get_embedding_service(container=Endpoints._container())

    @staticmethod
    def get_embedding_service_optional() -> EmbeddingServiceProtocol | None:
        """Get embedding service or None if not initialized."""
        from api.dependencies import get_embedding_service_optional

        return get_embedding_service_optional(container=Endpoints._container())

    @staticmethod
    def get_intent_classifier() -> Any:
        """Get intent classifier for search endpoints."""
        from api.dependencies import get_intent_classifier

        return get_intent_classifier(container=Endpoints._container())

    @staticmethod
    def get_intent_classifier_optional() -> Any:
        """Get intent classifier or None if not initialized."""
        from api.dependencies import get_intent_classifier_optional

        return get_intent_classifier_optional(container=Endpoints._container())

    # ── Optional Getters (return None instead of raising) ──────────────

    @staticmethod
    def get_relational_pool_optional() -> RelationalPool | None:
        """Get relational pool or None if not initialized."""
        from api.dependencies import get_relational_pool_optional

        return get_relational_pool_optional(container=Endpoints._container())

    @staticmethod
    def get_graph_pool_optional() -> GraphPool | None:
        """Get graph pool or None if not initialized."""
        from api.dependencies import get_graph_pool_optional

        return get_graph_pool_optional(container=Endpoints._container())

    @staticmethod
    def get_cache_client_optional() -> CachePool | None:
        """Get cache pool or None if not initialized."""
        from api.dependencies import get_cache_client_optional

        return get_cache_client_optional(container=Endpoints._container())

    # ── Lifecycle ──────────────────────────────────────────────────────

    @classmethod
    def initialize(cls, container: object) -> None:
        """Initialize all endpoints dependencies from container.

        This method is called by Container.startup() to ensure the
        global container is registered. The actual dependency resolution
        now happens via :mod:`api.dependencies` using the container.

        Args:
            container: Application container with all services.

        """
        from container import set_container

        set_container(container)

        log.info(
            "endpoints_initialized",
            relational_type=getattr(container, "relational_pool_type", "unknown"),
            graph_type=getattr(container, "graph_pool_type", None),
            cache_type=(
                type(getattr(container, "_cache_client", None)).__name__
                if hasattr(container, "_cache_client") and container._cache_client is not None
                else "none"
            ),
            llm_enabled=getattr(container, "_llm_client", None) is not None,
            search_enabled=getattr(container, "_local_search_engine", None) is not None,
        )

    @classmethod
    def reset(cls) -> None:
        """Reset all cached state for test isolation.

        Clears the global container so that subsequent dependency
        lookups will raise HTTPException(503) until a new container
        is set via :func:`container.set_container`.
        """
        import container as container_module

        with container_module._container_lock:
            container_module._container = None
