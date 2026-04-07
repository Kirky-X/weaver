# Copyright (c) 2026 KirkyX. All Rights Reserved
"""FastAPI dependency injection module.

This module provides FastAPI-compatible dependency functions for all services.
All dependencies return Protocol types, not concrete implementations.

Example:
    from fastapi import Depends
    from api.dependencies import get_relational_pool, get_graph_pool

    @router.get("/items")
    async def list_items(pool = Depends(get_relational_pool)):
        ...

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException

if TYPE_CHECKING:
    from container import Container
    from core.llm.client import LLMClient
    from core.protocols import CachePool, GraphPool, RelationalPool
    from core.services.pipeline_service import PipelineServiceImpl
    from core.services.task_registry import InMemoryTaskRegistry
    from modules.ingestion.scheduling.scheduler import SourceScheduler
    from modules.knowledge.search.engines.global_search import GlobalSearchEngine
    from modules.knowledge.search.engines.hybrid_search import HybridSearchEngine
    from modules.knowledge.search.engines.local_search import LocalSearchEngine
    from modules.storage import SourceAuthorityRepo, VectorRepo
    from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo
    from modules.analytics.llm_failure.repo import LLMFailureRepo
    from modules.analytics.llm_usage.repo import LLMUsageRepo
    from modules.storage.graph_repo import GraphRepository

from api.endpoints._deps import Endpoints


def get_container() -> Container:
    """Get the application container.

    This is the recommended way to access the container in FastAPI endpoints.
    Use with FastAPI's Depends() pattern.

    Returns:
        Container instance.

    Raises:
        HTTPException: If container is not initialized.

    """
    import container as container_module

    if container_module._container is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return container_module._container


# ── Pool Dependencies (Protocol Types) ─────────────────────────────────


def get_relational_pool() -> RelationalPool:
    """FastAPI dependency for relational database pool.

    Returns either PostgreSQL or DuckDB pool based on configuration.

    Raises:
        HTTPException: If pool is not initialized.

    Returns:
        RelationalPool instance (PostgresPool or DuckDBPool).

    """
    return Endpoints.get_relational_pool()


def get_graph_pool() -> GraphPool:
    """FastAPI dependency for graph database pool.

    Returns either Neo4j or LadybugDB pool based on configuration.

    Raises:
        HTTPException: If pool is not initialized.

    Returns:
        GraphPool instance (Neo4jPool or LadybugPool).

    """
    return Endpoints.get_graph_pool()


def get_cache_client() -> CachePool:
    """FastAPI dependency for cache client.

    Raises:
        HTTPException: If client is not initialized.

    Returns:
        CachePool instance (RedisClient or CashewsRedisFallback).

    """
    return Endpoints.get_cache()


# ── Service Dependencies ──────────────────────────────────────────────


def get_llm_client() -> LLMClient:
    """FastAPI dependency for LLM client.

    Raises:
        HTTPException: If client is not initialized.

    Returns:
        LLMClient instance.

    """
    return Endpoints.get_llm()


def get_vector_repo() -> VectorRepo:
    """FastAPI dependency for vector repository.

    Raises:
        HTTPException: If repo is not initialized.

    Returns:
        VectorRepo instance.

    """
    return Endpoints.get_vector_repo()


def get_graph_repo() -> GraphRepository:
    """FastAPI dependency for graph repository.

    Raises:
        HTTPException: If repo is not initialized.

    Returns:
        GraphRepository instance with database-agnostic query builder.

    """
    return Endpoints.get_graph_repo()


def get_local_search_engine() -> LocalSearchEngine:
    """FastAPI dependency for local search engine.

    Raises:
        HTTPException: If engine is not initialized.

    Returns:
        LocalSearchEngine instance.

    """
    return Endpoints.get_local_engine()


def get_global_search_engine() -> GlobalSearchEngine:
    """FastAPI dependency for global search engine.

    Raises:
        HTTPException: If engine is not initialized.

    Returns:
        GlobalSearchEngine instance.

    """
    return Endpoints.get_global_engine()


def get_hybrid_search_engine() -> HybridSearchEngine:
    """FastAPI dependency for hybrid search engine.

    Raises:
        HTTPException: If engine is not initialized.

    Returns:
        HybridSearchEngine instance.

    """
    return Endpoints.get_hybrid_engine()


def get_source_scheduler() -> SourceScheduler:
    """FastAPI dependency for source scheduler.

    Raises:
        HTTPException: If scheduler is not initialized.

    Returns:
        SourceScheduler instance.

    """
    return Endpoints.get_scheduler()


def get_source_config_repo() -> SourceConfigRepo:
    """FastAPI dependency for source config repository.

    Raises:
        HTTPException: If repo is not initialized.

    Returns:
        SourceConfigRepo instance.

    """
    return Endpoints.get_source_config_repo()


def get_source_authority_repo() -> SourceAuthorityRepo:
    """FastAPI dependency for source authority repository.

    Raises:
        HTTPException: If repo is not initialized.

    Returns:
        SourceAuthorityRepo instance.

    """
    return Endpoints.get_source_authority_repo()


def get_llm_failure_repo() -> LLMFailureRepo:
    """FastAPI dependency for LLM failure repository.

    Raises:
        HTTPException: If repo is not initialized.

    Returns:
        LLMFailureRepo instance.

    """
    return Endpoints.get_llm_failure_repo()


def get_llm_usage_repo() -> LLMUsageRepo:
    """FastAPI dependency for LLM usage repository.

    Raises:
        HTTPException: If repo is not initialized.

    Returns:
        LLMUsageRepo instance.

    """
    return Endpoints.get_llm_usage_repo()


def get_pipeline_service() -> PipelineServiceImpl:
    """FastAPI dependency for pipeline service.

    Raises:
        HTTPException: If service is not initialized.

    Returns:
        PipelineServiceImpl instance.

    """
    return Endpoints.get_pipeline_service()


def get_task_registry() -> InMemoryTaskRegistry:
    """FastAPI dependency for task registry.

    Raises:
        HTTPException: If registry is not initialized.

    Returns:
        InMemoryTaskRegistry instance.

    """
    return Endpoints.get_task_registry()


# ── Type Aliases for Cleaner Signatures ────────────────────────────────

RelationalPoolDep = Annotated["RelationalPool", Depends(get_relational_pool)]
GraphPoolDep = Annotated["GraphPool", Depends(get_graph_pool)]
CachePoolDep = Annotated["CachePool", Depends(get_cache_client)]
LLMClientDep = Annotated["LLMClient", Depends(get_llm_client)]
VectorRepoDep = Annotated["VectorRepo", Depends(get_vector_repo)]
GraphRepoDep = Annotated["GraphRepository", Depends(get_graph_repo)]
LocalSearchEngineDep = Annotated["LocalSearchEngine", Depends(get_local_search_engine)]
GlobalSearchEngineDep = Annotated["GlobalSearchEngine", Depends(get_global_search_engine)]
HybridSearchEngineDep = Annotated["HybridSearchEngine", Depends(get_hybrid_search_engine)]
SourceSchedulerDep = Annotated["SourceScheduler", Depends(get_source_scheduler)]
SourceConfigRepoDep = Annotated["SourceConfigRepo", Depends(get_source_config_repo)]
SourceAuthorityRepoDep = Annotated["SourceAuthorityRepo", Depends(get_source_authority_repo)]
LLMUsageRepoDep = Annotated["LLMUsageRepo", Depends(get_llm_usage_repo)]
TaskRegistryDep = Annotated["InMemoryTaskRegistry", Depends(get_task_registry)]
