"""PostgreSQL async connection pool and SQLAlchemy session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.observability.logging import get_logger

log = get_logger("postgres")


class PostgresPool:
    """Manages the asyncpg connection pool via SQLAlchemy async engine."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def startup(self) -> None:
        """Initialize the async engine and session factory."""
        self._engine = create_async_engine(
            self._dsn,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        log.info("postgres_pool_started", dsn=self._dsn.split("@")[-1])

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
