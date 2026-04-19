# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Centralized dependency registry for API endpoints.

All endpoint modules use Endpoints.get_*() to obtain pool/client instances.
The Container calls register_endpoints() once at startup to inject all dependencies.

All getters return Protocol types, not concrete implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from core.llm import LLMClient
    from core.protocols import CachePool, GraphPool, RelationalPool
    from core.services.pipeline_service import PipelineServiceImpl
    from core.services.task_registry import InMemoryTaskRegistry
    from modules.analytics import LLMFailureRepo, LLMUsageRepo
    from modules.ingestion import SourceConfigRepo, SourceScheduler
    from modules.knowledge.search import GlobalSearchEngine, HybridSearchEngine, LocalSearchEngine
    from modules.storage import SourceAuthorityRepo, VectorRepo
    from modules.storage.graph_repo import GraphRepository


class Endpoints:
    """Centralized dependency registry for all endpoint modules.

    All pool/client instances are set once by Container.register_endpoints()
    at application startup. Endpoint modules access dependencies via
    Endpoints.get_*() static methods.

    All types are Protocol types, enabling database abstraction.
    """

    # ── Pool Instances (Protocol Types) ───────────────────────────────
    _relational_pool: RelationalPool | None = None
    _graph_pool: GraphPool | None = None
    _graph_pool_type: str | None = None
    _cache: CachePool | None = None
    _relational_pool_type: str | None = None

    # ── Service Instances ─────────────────────────────────────────────
    _llm: LLMClient | None = None
    _local_engine: LocalSearchEngine | None = None
    _global_engine: GlobalSearchEngine | None = None
    _hybrid_engine: HybridSearchEngine | None = None
    _vector_repo: VectorRepo | None = None
    _graph_repo: GraphRepository | None = None
    _scheduler: SourceScheduler | None = None
    _source_config_repo: SourceConfigRepo | None = None
    _source_authority_repo: SourceAuthorityRepo | None = None
    _llm_failure_repo: LLMFailureRepo | None = None
    _llm_usage_repo: LLMUsageRepo | None = None
    _pipeline_service: PipelineServiceImpl | None = None
    _task_registry: InMemoryTaskRegistry | None = None

    # ── Relational Pool ───────────────────────────────────────────────

    @staticmethod
    def get_relational_pool() -> RelationalPool:
        """Get relational database pool (PostgreSQL or DuckDB)."""
        if Endpoints._relational_pool is None:
            raise HTTPException(503, detail="Relational pool not initialized")
        return Endpoints._relational_pool

    # ── Graph Pool ────────────────────────────────────────────────────

    @staticmethod
    def get_graph_pool() -> GraphPool:
        """Get graph database pool (Neo4j or LadybugDB)."""
        if Endpoints._graph_pool is None:
            raise HTTPException(503, detail="Graph pool not initialized")
        return Endpoints._graph_pool

    @staticmethod
    def get_graph_pool_type() -> str:
        """Get graph database type ('neo4j' or 'ladybug')."""
        if Endpoints._graph_pool_type is None:
            raise HTTPException(503, detail="Graph pool type not initialized")
        return Endpoints._graph_pool_type

    @staticmethod
    def get_relational_type() -> str:
        """Get relational database type ('postgres' or 'duckdb')."""
        return Endpoints._relational_pool_type or "unknown"

    @staticmethod
    def get_graph_type() -> str:
        """Get graph database type ('neo4j' or 'ladybug')."""
        return Endpoints._graph_pool_type or "unknown"

    @staticmethod
    def get_cache_type() -> str:
        """Get cache type ('redis' or 'cashews')."""
        if Endpoints._cache is not None:
            return type(Endpoints._cache).__name__
        return "none"

    # ── Cache ─────────────────────────────────────────────────────────

    @staticmethod
    def get_cache_pool() -> CachePool:
        """Get cache pool (Redis or in-memory fallback)."""
        if Endpoints._cache is None:
            raise HTTPException(503, detail="Cache pool not initialized")
        return Endpoints._cache

    # ── LLM ───────────────────────────────────────────────────────────

    @staticmethod
    def get_llm_client() -> LLMClient:
        """Get LLM client."""
        if Endpoints._llm is None:
            raise HTTPException(503, detail="LLM client not initialized")
        return Endpoints._llm

    @staticmethod
    def get_llm_client_optional() -> LLMClient | None:
        """Get LLM client or None if unavailable."""
        return Endpoints._llm

    # ── Search Engines ────────────────────────────────────────────────

    @staticmethod
    def get_local_search_engine() -> LocalSearchEngine:
        """Get local search engine."""
        if Endpoints._local_engine is None:
            raise HTTPException(503, detail="Search service not initialized")
        return Endpoints._local_engine

    @staticmethod
    def get_local_search_engine_optional() -> LocalSearchEngine | None:
        """Get local search engine or None if unavailable."""
        return Endpoints._local_engine

    @staticmethod
    def get_global_search_engine() -> GlobalSearchEngine:
        """Get global search engine."""
        if Endpoints._global_engine is None:
            raise HTTPException(503, detail="Search service not initialized")
        return Endpoints._global_engine

    @staticmethod
    def get_hybrid_search_engine() -> HybridSearchEngine:
        """Get hybrid search engine."""
        if Endpoints._hybrid_engine is None:
            raise HTTPException(503, detail="Hybrid search service not initialized")
        return Endpoints._hybrid_engine

    # ── Repositories ──────────────────────────────────────────────────

    @staticmethod
    def get_vector_repo() -> VectorRepo:
        """Get vector repository."""
        if Endpoints._vector_repo is None:
            raise HTTPException(503, detail="Vector store not initialized")
        return Endpoints._vector_repo

    @staticmethod
    def get_graph_repo() -> GraphRepository:
        """Get graph repository with database-agnostic query builder."""
        if Endpoints._graph_repo is None:
            raise HTTPException(503, detail="Graph repository not initialized")
        return Endpoints._graph_repo

    # ── Scheduler ──────────────────────────────────────────────────────

    @staticmethod
    def get_source_scheduler() -> SourceScheduler:
        """Get source scheduler."""
        if Endpoints._scheduler is None:
            raise HTTPException(503, detail="Source scheduler not initialized")
        return Endpoints._scheduler

    # ── Config Repos ──────────────────────────────────────────────────

    @staticmethod
    def get_source_config_repo() -> SourceConfigRepo:
        """Get source config repository."""
        if Endpoints._source_config_repo is None:
            raise HTTPException(503, detail="Source config repository not initialized")
        return Endpoints._source_config_repo

    @staticmethod
    def get_source_authority_repo() -> SourceAuthorityRepo:
        """Get source authority repository."""
        if Endpoints._source_authority_repo is None:
            raise HTTPException(503, detail="Source authority repo not initialized")
        return Endpoints._source_authority_repo

    @staticmethod
    def get_llm_failure_repo() -> LLMFailureRepo:
        """Get LLM failure repository."""
        if Endpoints._llm_failure_repo is None:
            raise HTTPException(503, detail="LLM failure repo not initialized")
        return Endpoints._llm_failure_repo

    @staticmethod
    def get_llm_usage_repo() -> LLMUsageRepo:
        """Get LLM usage repository."""
        if Endpoints._llm_usage_repo is None:
            raise HTTPException(503, detail="LLM usage repo not initialized")
        return Endpoints._llm_usage_repo

    # ── Pipeline Service ───────────────────────────────────────────────

    @staticmethod
    def get_pipeline_service() -> PipelineServiceImpl:
        """Get the pipeline service."""
        if Endpoints._pipeline_service is None:
            raise HTTPException(503, detail="Pipeline service not initialized")
        return Endpoints._pipeline_service

    # ── Task Registry ──────────────────────────────────────────────────

    @staticmethod
    def get_task_registry() -> InMemoryTaskRegistry:
        """Get the task registry for background task tracking."""
        if Endpoints._task_registry is None:
            raise HTTPException(503, detail="Task registry not initialized")
        return Endpoints._task_registry

    # ── Optional Getters (return None instead of raising) ──────────────

    @staticmethod
    def get_relational_pool_optional() -> RelationalPool | None:
        """Get relational pool or None if not initialized."""
        return Endpoints._relational_pool

    @staticmethod
    def get_graph_pool_optional() -> GraphPool | None:
        """Get graph pool or None if not initialized."""
        return Endpoints._graph_pool

    @staticmethod
    def get_cache_pool_optional() -> CachePool | None:
        """Get cache pool or None if not initialized."""
        return Endpoints._cache
