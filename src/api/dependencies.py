# Copyright (c) 2026 KirkyX. All Rights Reserved
"""FastAPI dependency injection module.

This module provides FastAPI-compatible dependency functions for all services.
All dependencies return Protocol types, not concrete implementations.

Dependencies access the container via the public ``container.get_container()``
function (no private attribute access). Each ``get_*`` function is a true
FastAPI Depends that receives the container via ``Depends(get_container)``.

Example:
    from fastapi import Depends
    from api.dependencies import get_relational_pool, get_graph_pool

    @router.get("/items")
    async def list_items(pool: RelationalPool = Depends(get_relational_pool)):
        ...

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException

if TYPE_CHECKING:
    from container import Container
    from core.llm import LLMClient
    from core.protocols import (
        CachePool,
        EmbeddingServiceProtocol,
        GraphPool,
        PipelineService,
        RelationalPool,
        TaskRegistryService,
        VectorRepository,
    )
    from core.saga import SagaOrchestrator
    from modules.analytics import LLMFailureRepo, LLMUsageRepo
    from modules.ingestion import SourceConfigRepo, SourceScheduler
    from modules.knowledge.search import (
        GlobalSearchEngine,
        HybridSearchEngine,
        LocalSearchEngine,
    )
    from modules.storage import SourceAuthorityRepo
    from modules.storage.graph_repo import GraphRepository


def get_container() -> Container:
    """FastAPI dependency for the application container.

    Uses the public ``container.get_container()`` function (thread-safe)
    rather than accessing private module attributes.

    Returns:
        Container instance.

    Raises:
        HTTPException: 503 if container is not initialized.

    """
    from container import get_container as _get_container

    try:
        return _get_container()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Service not initialized")


# ── Pool Dependencies (Protocol Types) ─────────────────────────────────


def get_relational_pool(
    container: Container = Depends(get_container),
) -> RelationalPool:
    """FastAPI dependency for relational database pool.

    Returns either PostgreSQL or DuckDB pool based on configuration.

    Raises:
        HTTPException: 503 if pool is not initialized.

    Returns:
        RelationalPool instance (PostgresPool or DuckDBPool).

    """
    try:
        return container.relational_pool()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Relational pool not initialized")


def get_graph_pool(
    container: Container = Depends(get_container),
) -> GraphPool:
    """FastAPI dependency for graph database pool.

    Returns either Neo4j or LadybugDB pool based on configuration.

    Raises:
        HTTPException: 503 if pool is not initialized.

    Returns:
        GraphPool instance (Neo4jPool or LadybugPool).

    """
    pool = container.graph_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Graph pool not initialized")
    return pool


def get_graph_pool_type(container: Container = Depends(get_container)) -> str:
    """FastAPI dependency for graph database type.

    Returns:
        String identifier ('neo4j' or 'ladybug').

    Raises:
        HTTPException: 503 if pool type is not initialized.

    """
    pool_type = container.graph_pool_type
    if pool_type is None:
        raise HTTPException(status_code=503, detail="Graph pool type not initialized")
    return pool_type


def get_relational_type(container: Container = Depends(get_container)) -> str:
    """FastAPI dependency for relational database type.

    Returns:
        'postgres' or 'duckdb'.

    """
    try:
        return container.relational_pool_type
    except RuntimeError:
        return "unknown"


def get_graph_type(container: Container = Depends(get_container)) -> str:
    """FastAPI dependency for graph database type.

    Returns:
        'neo4j', 'ladybug', or 'unknown'.

    """
    return container.graph_pool_type or "unknown"


def get_cache_type(container: Container = Depends(get_container)) -> str:
    """FastAPI dependency for cache type.

    Returns:
        Cache type string ('redis', 'cashews') or class name, or 'none'.

    """
    try:
        cache = container.cache_client()
        # Prefer cache_type attribute (FallbackCachePool exposes it,
        # returning 'redis' or 'cashews' based on primary health).
        if hasattr(cache, "cache_type"):
            return cache.cache_type
        return type(cache).__name__
    except RuntimeError:
        return "none"


def get_cache_client(
    container: Container = Depends(get_container),
) -> CachePool:
    """FastAPI dependency for cache pool.

    Raises:
        HTTPException: 503 if pool is not initialized.

    Returns:
        CachePool instance (RedisClient or CashewsClient).

    """
    try:
        return container.cache_client()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Cache pool not initialized")


# ── Service Dependencies ──────────────────────────────────────────────


def get_llm_client(
    container: Container = Depends(get_container),
) -> LLMClient:
    """FastAPI dependency for LLM client.

    Raises:
        HTTPException: 503 if client is not initialized.

    Returns:
        LLMClient instance.

    """
    client = container.llm_client()
    if client is None:
        raise HTTPException(status_code=503, detail="LLM client not initialized")
    return client


def get_vector_repo(
    container: Container = Depends(get_container),
) -> VectorRepository:
    """FastAPI dependency for vector repository.

    Raises:
        HTTPException: 503 if repo is not initialized.

    Returns:
        VectorRepo instance.

    """
    try:
        return container.vector_repo()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Vector store not initialized")


def get_graph_repo(
    container: Container = Depends(get_container),
) -> GraphRepository:
    """FastAPI dependency for graph repository.

    Raises:
        HTTPException: 503 if repo is not initialized.

    Returns:
        GraphRepository instance with database-agnostic query builder.

    """
    try:
        return container.graph_repo()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Graph repository not initialized")


def get_local_search_engine(
    container: Container = Depends(get_container),
) -> LocalSearchEngine:
    """FastAPI dependency for local search engine.

    Raises:
        HTTPException: 503 if engine is not initialized.

    Returns:
        LocalSearchEngine instance.

    """
    engine = container.local_search_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Search service not initialized")
    return engine


def get_global_search_engine(
    container: Container = Depends(get_container),
) -> GlobalSearchEngine:
    """FastAPI dependency for global search engine.

    Raises:
        HTTPException: 503 if engine is not initialized.

    Returns:
        GlobalSearchEngine instance.

    """
    engine = container.global_search_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Search service not initialized")
    return engine


def get_hybrid_engine(
    container: Container = Depends(get_container),
) -> HybridSearchEngine:
    """FastAPI dependency for hybrid search engine.

    Raises:
        HTTPException: 503 if engine is not initialized.

    Returns:
        HybridSearchEngine instance.

    """
    engine = container.hybrid_search_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Hybrid search service not initialized")
    return engine


def get_source_scheduler(
    container: Container = Depends(get_container),
) -> SourceScheduler:
    """FastAPI dependency for source scheduler.

    Raises:
        HTTPException: 503 if scheduler is not initialized.

    Returns:
        SourceScheduler instance.

    """
    try:
        return container.source_scheduler()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Source scheduler not initialized")


def get_smart_fetcher(
    container: Container = Depends(get_container),
) -> Any:
    """FastAPI dependency for smart fetcher.

    Raises:
        HTTPException: 503 if smart fetcher is not initialized.

    Returns:
        SmartFetcher instance.

    """
    try:
        return container.smart_fetcher()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Smart fetcher not initialized")


def get_source_config_repo(
    container: Container = Depends(get_container),
) -> SourceConfigRepo:
    """FastAPI dependency for source config repository.

    Raises:
        HTTPException: 503 if repo is not initialized.

    Returns:
        SourceConfigRepo instance.

    """
    try:
        return container.source_config_repo()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Source config repository not initialized")


def get_source_authority_repo(
    container: Container = Depends(get_container),
) -> SourceAuthorityRepo:
    """FastAPI dependency for source authority repository.

    Raises:
        HTTPException: 503 if repo is not initialized.

    Returns:
        SourceAuthorityRepo instance.

    """
    try:
        return container.source_authority_repo()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Source authority repo not initialized")


def get_llm_failure_repo(
    container: Container = Depends(get_container),
) -> LLMFailureRepo:
    """FastAPI dependency for LLM failure repository.

    Raises:
        HTTPException: 503 if repo is not initialized.

    Returns:
        LLMFailureRepo instance.

    """
    try:
        return container.llm_failure_repo()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="LLM failure repo not initialized")


def get_llm_usage_repo(
    container: Container = Depends(get_container),
) -> LLMUsageRepo:
    """FastAPI dependency for LLM usage repository.

    Raises:
        HTTPException: 503 if repo is not initialized.

    Returns:
        LLMUsageRepo instance.

    """
    try:
        return container.llm_usage_repo()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="LLM usage repo not initialized")


def get_saga_orchestrator(
    container: Container = Depends(get_container),
) -> SagaOrchestrator:
    """FastAPI dependency for Saga orchestrator.

    Raises:
        HTTPException: 503 if orchestrator is not initialized.

    Returns:
        SagaOrchestrator instance.

    """
    try:
        return container.saga_orchestrator()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Saga orchestrator not initialized")


def get_pipeline_service(
    container: Container = Depends(get_container),
) -> PipelineService:
    """FastAPI dependency for pipeline service.

    Raises:
        HTTPException: 503 if service is not initialized.

    Returns:
        PipelineService instance (Protocol type; concrete impl is PipelineServiceImpl).

    """
    try:
        return container.pipeline_service()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Pipeline service not initialized")


def get_task_registry(
    container: Container = Depends(get_container),
) -> TaskRegistryService:
    """FastAPI dependency for task registry.

    Raises:
        HTTPException: 503 if registry is not initialized.

    Returns:
        TaskRegistryService instance (Protocol type; concrete impl is InMemoryTaskRegistry).

    """
    try:
        return container.task_registry()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Task registry not initialized")


def get_embedding_service(
    container: Container = Depends(get_container),
) -> EmbeddingServiceProtocol:
    """FastAPI dependency for embedding service.

    Raises:
        HTTPException: 503 if service is not initialized.

    Returns:
        EmbeddingServiceProtocol instance.

    """
    service = getattr(container, "_embedding_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Embedding service not initialized")
    return service


def get_intent_classifier(
    container: Container = Depends(get_container),
) -> Any:
    """FastAPI dependency for intent classifier.

    Raises:
        HTTPException: 503 if classifier is not initialized.

    Returns:
        Intent classifier instance.

    """
    service = getattr(container, "_intent_classifier", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Intent classifier not initialized")
    return service


# ── Optional Getters (return None instead of raising) ─────────────────


def get_relational_pool_optional(
    container: Container = Depends(get_container),
) -> RelationalPool | None:
    """Get relational pool or None if not initialized."""
    try:
        return container.relational_pool()
    except RuntimeError:
        return None


def get_graph_pool_optional(
    container: Container = Depends(get_container),
) -> GraphPool | None:
    """Get graph pool or None if not initialized."""
    return container.graph_pool()


def get_cache_client_optional(
    container: Container = Depends(get_container),
) -> CachePool | None:
    """Get cache pool or None if not initialized."""
    try:
        return container.cache_client()
    except RuntimeError:
        return None


def get_llm_client_optional(
    container: Container = Depends(get_container),
) -> LLMClient | None:
    """Get LLM client or None if unavailable."""
    return container.llm_client()


def get_embedding_service_optional(
    container: Container = Depends(get_container),
) -> EmbeddingServiceProtocol | None:
    """Get embedding service or None if not initialized."""
    return getattr(container, "_embedding_service", None)


def get_intent_classifier_optional(
    container: Container = Depends(get_container),
) -> Any:
    """Get intent classifier or None if not initialized."""
    return getattr(container, "_intent_classifier", None)


# ── Type Aliases for Cleaner Signatures ────────────────────────────────

RelationalPoolDep = Annotated["RelationalPool", Depends(get_relational_pool)]
GraphPoolDep = Annotated["GraphPool", Depends(get_graph_pool)]
CachePoolDep = Annotated["CachePool", Depends(get_cache_client)]
LLMClientDep = Annotated["LLMClient", Depends(get_llm_client)]
VectorRepoDep = Annotated["VectorRepository", Depends(get_vector_repo)]
GraphRepoDep = Annotated["GraphRepository", Depends(get_graph_repo)]
LocalSearchEngineDep = Annotated["LocalSearchEngine", Depends(get_local_search_engine)]
GlobalSearchEngineDep = Annotated["GlobalSearchEngine", Depends(get_global_search_engine)]
HybridSearchEngineDep = Annotated["HybridSearchEngine", Depends(get_hybrid_engine)]
SourceSchedulerDep = Annotated["SourceScheduler", Depends(get_source_scheduler)]
SourceConfigRepoDep = Annotated["SourceConfigRepo", Depends(get_source_config_repo)]
SourceAuthorityRepoDep = Annotated["SourceAuthorityRepo", Depends(get_source_authority_repo)]
LLMUsageRepoDep = Annotated["LLMUsageRepo", Depends(get_llm_usage_repo)]
