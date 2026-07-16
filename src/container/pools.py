# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Database and cache pool initialization for the container."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings
    from core.cache import CashewsClient, FallbackCachePool, RedisClient
    from core.db import DatabaseStrategy
    from core.protocols import CachePool, GraphPool, RelationalPool


class ContainerPoolsMixin:
    """Database and cache pool management mixin.

    Provides initialization and access to relational database pools,
    graph database pools, and Redis cache pools.
    """

    # ── Private attributes (defined in Container.__init__) ─────────
    _settings: Settings | None
    _strategy: DatabaseStrategy | None
    _cache_client: RedisClient | CashewsClient | FallbackCachePool | None

    # ── Database Pools ──────────────────────────────────────────

    async def init_strategy(self) -> DatabaseStrategy:
        """Initialize database strategy with failover support."""
        if self._strategy is None:
            from core.db import create_strategy

            self._strategy = await create_strategy(
                pg_settings=self._settings.postgres,
                neo4j_settings=self._settings.neo4j,
                duckdb_settings=self._settings.duckdb,
                ladybug_settings=self._settings.ladybug,
            )
            from core.observability import get_logger

            log = get_logger(__name__)
            log.info(
                "database_strategy_initialized",
                relational_type=self._strategy.relational_type.value,
                graph_type=self._strategy.graph_type,
            )
        return self._strategy

    def relational_pool(self) -> RelationalPool:
        """Get relational database pool (PostgreSQL or DuckDB)."""
        if self._strategy is None:
            raise RuntimeError("Database strategy not initialized. Call init_strategy() first.")
        return self._strategy.relational_pool

    def graph_pool(self) -> GraphPool | None:
        """Get graph database pool (Neo4j or LadybugDB), or None if unavailable."""
        if self._strategy is None:
            return None
        return self._strategy.graph_pool

    @property
    def relational_pool_type(self) -> str:
        """Get the type of relational database being used.

        Returns:
            "postgres" or "duckdb".

        """
        if self._strategy is None:
            raise RuntimeError("Database strategy not initialized. Call init_strategy() first.")
        return self._strategy.relational_type.value

    @property
    def graph_pool_type(self) -> str | None:
        """Get the type of graph database being used.

        Returns:
            "neo4j", "ladybug", or None if unavailable.

        """
        if self._strategy is None:
            return None
        return self._strategy.graph_type

    async def init_cache_client(self) -> RedisClient | CashewsClient:
        """Initialize cache pool with runtime fallback support.

        Creates a FallbackCachePool that holds both RedisClient (primary)
        and CashewsClient (fallback). When Redis operations fail at runtime,
        the pool automatically degrades to CashewsClient. Periodic health
        probes restore Redis when it recovers.

        Returns:
            RedisClient or CashewsClient instance (wrapped in FallbackCachePool).

        """
        if self._cache_client is None:
            from core.cache import CashewsClient, FallbackCachePool, RedisClient
            from core.observability import get_logger

            log = get_logger(__name__)

            # Create both clients
            primary = RedisClient(self._settings.redis.url)
            fallback = CashewsClient()

            # Start both clients
            primary_ok = False
            try:
                await primary.startup()
                primary_ok = True
                log.info("redis_initialized")
            except Exception as exc:
                log.warning("redis_unavailable_fallback_to_cashews", error=str(exc))

            await fallback.startup()
            log.info("cashews_client_initialized")

            # Wrap in FallbackCachePool for runtime degradation
            pool = FallbackCachePool(primary=primary, fallback=fallback)

            # If primary failed at startup, mark as degraded
            if not primary_ok:
                pool._primary_healthy = False
                pool._set_fallback_active(1)

            self._cache_client = pool

        return self._cache_client

    def cache_client(self) -> CachePool:
        """Get cache pool (Redis or in-memory fallback).

        Returns:
            CachePool implementation (RedisClient or CashewsClient).

        """
        if self._cache_client is None:
            raise RuntimeError("Cache pool not initialized. Call init_cache_client() first.")
        return self._cache_client
