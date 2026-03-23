# Copyright (c) 2026 KirkyX. All Rights Reserved
"""PostgreSQL async connection pool and SQLAlchemy session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.observability.logging import get_logger
from core.observability.metrics import MetricsCollector

log = get_logger("postgres")


class PostgresPool:
    """Manages the asyncpg connection pool via SQLAlchemy async engine.

    Provides connection pool management with monitoring and dynamic
    adjustment capabilities.

    Args:
        dsn: Database connection string.
        pool_size: Initial pool size (default 20).
        max_overflow: Maximum overflow connections (default 10).
        pool_pre_ping: Enable connection health checks (default True).
    """

    def __init__(
        self,
        dsn: str,
        pool_size: int = 20,
        max_overflow: int = 10,
        pool_pre_ping: bool = True,
    ) -> None:
        self._dsn = dsn
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_pre_ping = pool_pre_ping
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def startup(self) -> None:
        """Initialize the async engine and session factory."""
        self._engine = create_async_engine(
            self._dsn,
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_pre_ping=self._pool_pre_ping,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            log.info(
                "postgres_pool_started",
                dsn=self._dsn.split("@")[-1],
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
            )
        except Exception as exc:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            log.error("postgres_connection_failed", error=str(exc))
            raise ConnectionError(f"Failed to connect to PostgreSQL: {exc}") from exc

    async def shutdown(self) -> None:
        """Close the async engine and release connections."""
        if self._engine:
            await self._engine.dispose()
            log.info("postgres_pool_closed")

    @property
    def engine(self) -> AsyncEngine:
        """Return the async engine.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._engine is None:
            raise RuntimeError("PostgresPool not started. Call startup() first.")
        return self._engine

    def session(self) -> AsyncSession:
        """Create a new async session.

        Returns:
            A new AsyncSession instance.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._session_factory is None:
            raise RuntimeError("PostgresPool not started. Call startup() first.")
        return self._session_factory()

    @asynccontextmanager
    async def session_context(self) -> AsyncIterator[AsyncSession]:
        """Context manager for database sessions with automatic cleanup.

        Yields:
            AsyncSession instance.

        Example:
            async with pool.session_context() as session:
                result = await session.execute(query)
        """
        session = self.session()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    def get_pool_stats(self) -> dict:
        """Get connection pool statistics.

        Returns:
            Dict with pool_size, overflow, checked_in, checked_out,
            overflow_invalid, and utilization.
        """
        if self._engine is None:
            return {
                "pool_size": 0,
                "overflow": 0,
                "checked_in": 0,
                "checked_out": 0,
                "overflow_invalid": 0,
                "utilization": 0.0,
            }

        pool = self._engine.pool
        stats = {
            "pool_size": pool.size(),  # type: ignore[attr-defined]
            "overflow": pool.overflow(),  # type: ignore[attr-defined]
            "checked_in": pool.checkedin(),  # type: ignore[attr-defined]
            "checked_out": pool.checkedout(),  # type: ignore[attr-defined]
            "overflow_invalid": pool.overflow_invalid(),  # type: ignore[attr-defined]
        }

        total_capacity = self._pool_size + self._max_overflow
        if total_capacity > 0:
            stats["utilization"] = stats["checked_out"] / total_capacity
        else:
            stats["utilization"] = 0.0

        return stats

    async def record_metrics(self) -> None:
        """Record pool metrics to Prometheus."""
        stats = self.get_pool_stats()

        MetricsCollector.db_pool_size.labels(pool="postgres").set(stats["pool_size"])
        MetricsCollector.db_pool_checked_out.labels(pool="postgres").set(stats["checked_out"])
        MetricsCollector.db_pool_utilization.labels(pool="postgres").set(stats["utilization"])

        log.debug(
            "postgres_pool_stats",
            **stats,
        )
