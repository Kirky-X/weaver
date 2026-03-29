# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Centralized dependency registry for API endpoints.

All endpoint modules use Endpoints.get_*() to obtain pool/client instances.
The Container calls register_endpoints() once at startup to inject all dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from core.cache.redis import RedisClient
    from core.db.neo4j import Neo4jPool
    from core.db.postgres import PostgresPool
    from core.llm.client import LLMClient
    from modules.collector.source_scheduler import SourceScheduler
    from modules.search.engines.global_search import GlobalSearchEngine
    from modules.search.engines.hybrid_search import HybridSearchEngine
    from modules.search.engines.local_search import LocalSearchEngine
    from modules.source.source_authority_repo import SourceAuthorityRepo
    from modules.source.source_config_repo import SourceConfigRepo
    from modules.storage.llm_failure_repo import LLMFailureRepo
    from modules.storage.llm_usage_repo import LLMUsageRepo
    from modules.storage.vector_repo import VectorRepo


class Endpoints:
    """Centralized dependency registry for all endpoint modules.

    All pool/client instances are set once by Container.register_endpoints()
    at application startup. Endpoint modules access dependencies via
    Endpoints.get_*() static methods.
    """

    _postgres: PostgresPool | None = None
    _neo4j: Neo4jPool | None = None
    _redis: RedisClient | None = None
    _llm: LLMClient | None = None
    _local_engine: LocalSearchEngine | None = None
    _global_engine: GlobalSearchEngine | None = None
    _hybrid_engine: HybridSearchEngine | None = None
    _vector_repo: VectorRepo | None = None
    _scheduler: SourceScheduler | None = None
    _source_config_repo: SourceConfigRepo | None = None
    _source_authority_repo: SourceAuthorityRepo | None = None
    _llm_failure_repo: LLMFailureRepo | None = None
    _llm_usage_repo: LLMUsageRepo | None = None

    # ── Postgres ────────────────────────────────────────────────

    @staticmethod
    def get_postgres_pool() -> PostgresPool:
        if Endpoints._postgres is None:
            raise HTTPException(503, detail="Postgres pool not initialized")
        return Endpoints._postgres

    # ── Neo4j ───────────────────────────────────────────────────

    @staticmethod
    def get_neo4j_pool() -> Neo4jPool:
        if Endpoints._neo4j is None:
            raise HTTPException(503, detail="Neo4j pool not initialized")
        return Endpoints._neo4j

    # ── Redis ──────────────────────────────────────────────────

    @staticmethod
    def get_redis() -> RedisClient:
        if Endpoints._redis is None:
            raise HTTPException(503, detail="Redis client not initialized")
        return Endpoints._redis

    # ── LLM ─────────────────────────────────────────────────────

    @staticmethod
    def get_llm() -> LLMClient:
        if Endpoints._llm is None:
            raise HTTPException(503, detail="LLM client not initialized")
        return Endpoints._llm

    # ── Search engines ───────────────────────────────────────────

    @staticmethod
    def get_local_engine() -> LocalSearchEngine:
        if Endpoints._local_engine is None:
            raise HTTPException(503, detail="Search service not initialized")
        return Endpoints._local_engine

    @staticmethod
    def get_global_engine() -> GlobalSearchEngine:
        if Endpoints._global_engine is None:
            raise HTTPException(503, detail="Search service not initialized")
        return Endpoints._global_engine

    @staticmethod
    def get_hybrid_engine() -> HybridSearchEngine:
        if Endpoints._hybrid_engine is None:
            raise HTTPException(503, detail="Hybrid search service not initialized")
        return Endpoints._hybrid_engine

    # ── Vector repo ──────────────────────────────────────────────

    @staticmethod
    def get_vector_repo() -> VectorRepo:
        if Endpoints._vector_repo is None:
            raise HTTPException(503, detail="Vector store not initialized")
        return Endpoints._vector_repo

    # ── Scheduler ────────────────────────────────────────────────

    @staticmethod
    def get_scheduler() -> SourceScheduler:
        if Endpoints._scheduler is None:
            raise HTTPException(503, detail="Source scheduler not initialized")
        return Endpoints._scheduler

    # ── Repos ───────────────────────────────────────────────────

    @staticmethod
    def get_source_config_repo() -> SourceConfigRepo:
        if Endpoints._source_config_repo is None:
            raise HTTPException(503, detail="Source config repository not initialized")
        return Endpoints._source_config_repo

    @staticmethod
    def get_source_authority_repo() -> SourceAuthorityRepo:
        if Endpoints._source_authority_repo is None:
            raise HTTPException(503, detail="Source authority repo not initialized")
        return Endpoints._source_authority_repo

    @staticmethod
    def get_llm_failure_repo() -> LLMFailureRepo:
        if Endpoints._llm_failure_repo is None:
            raise HTTPException(503, detail="LLM failure repo not initialized")
        return Endpoints._llm_failure_repo

    @staticmethod
    def get_llm_usage_repo() -> LLMUsageRepo:
        if Endpoints._llm_usage_repo is None:
            raise HTTPException(503, detail="LLM usage repo not initialized")
        return Endpoints._llm_usage_repo
