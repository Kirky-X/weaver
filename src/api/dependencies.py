# Copyright (c) 2026 KirkyX. All Rights Reserved
"""FastAPI dependency injection module.

This module provides FastAPI-compatible dependency functions for all services.
These can be used with FastAPI's Depends() pattern for cleaner endpoint signatures.

Example:
    from fastapi import Depends
    from api.dependencies import get_postgres_pool, get_redis_client

    @router.get("/items")
    async def list_items(pool = Depends(get_postgres_pool)):
        ...

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException

if TYPE_CHECKING:
    from container import Container
    from core.cache.redis import RedisClient
    from core.db.neo4j import Neo4jPool
    from core.db.postgres import PostgresPool
    from core.llm.client import LLMClient
    from modules.ingestion.scheduling.scheduler import SourceScheduler
    from modules.knowledge.search.engines.global_search import GlobalSearchEngine
    from modules.knowledge.search.engines.hybrid_search import HybridSearchEngine
    from modules.knowledge.search.engines.local_search import LocalSearchEngine
    from modules.storage.postgres.source_authority_repo import SourceAuthorityRepo
    from modules.ingestion.scheduling.source_config_repo import SourceConfigRepo
    from modules.storage.postgres.article_repo import ArticleRepo
    from modules.storage.llm_usage_repo import LLMUsageRepo
    from modules.storage.postgres.vector_repo import VectorRepo

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


def get_postgres_pool() -> PostgresPool:
    """FastAPI dependency for PostgreSQL connection pool.

    Raises:
        HTTPException: If pool is not initialized.

    Returns:
        PostgresPool instance.

    """
    return Endpoints.get_postgres_pool()


def get_redis_client() -> RedisClient:
    """FastAPI dependency for Redis client.

    Raises:
        HTTPException: If client is not initialized.

    Returns:
        RedisClient instance.

    """
    return Endpoints.get_redis()


def get_neo4j_pool() -> Neo4jPool:
    """FastAPI dependency for Neo4j connection pool.

    Raises:
        HTTPException: If pool is not initialized.

    Returns:
        Neo4jPool instance.

    """
    return Endpoints.get_neo4j_pool()


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


def get_article_repo(pool: Annotated[PostgresPool, Depends(get_postgres_pool)]) -> ArticleRepo:
    """FastAPI dependency for article repository.

    Args:
        pool: PostgreSQL pool from dependency.

    Returns:
        ArticleRepo instance.

    """
    from modules.storage.postgres.article_repo import ArticleRepo

    return ArticleRepo(pool)


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


def get_llm_failure_repo() -> Any:
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


# Type aliases for cleaner endpoint signatures
PostgresPoolDep = Annotated["PostgresPool", Depends(get_postgres_pool)]
RedisClientDep = Annotated["RedisClient", Depends(get_redis_client)]
Neo4jPoolDep = Annotated["Neo4jPool", Depends(get_neo4j_pool)]
LLMClientDep = Annotated["LLMClient", Depends(get_llm_client)]
VectorRepoDep = Annotated["VectorRepo", Depends(get_vector_repo)]
ArticleRepoDep = Annotated["ArticleRepo", Depends(get_article_repo)]
LocalSearchEngineDep = Annotated["LocalSearchEngine", Depends(get_local_search_engine)]
GlobalSearchEngineDep = Annotated["GlobalSearchEngine", Depends(get_global_search_engine)]
HybridSearchEngineDep = Annotated["HybridSearchEngine", Depends(get_hybrid_search_engine)]
SourceSchedulerDep = Annotated["SourceScheduler", Depends(get_source_scheduler)]
SourceConfigRepoDep = Annotated["SourceConfigRepo", Depends(get_source_config_repo)]
SourceAuthorityRepoDep = Annotated["SourceAuthorityRepo", Depends(get_source_authority_repo)]
LLMUsageRepoDep = Annotated["LLMUsageRepo", Depends(get_llm_usage_repo)]
