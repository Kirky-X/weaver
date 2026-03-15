"""Neo4j async driver wrapper."""

from __future__ import annotations

from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.api import Auth

from core.observability.logging import get_logger

log = get_logger("neo4j")


class Neo4jPool:
    """Wraps the official Neo4j async driver for connection management."""

    def __init__(self, uri: str, auth: tuple[str, str]) -> None:
        self._uri = uri
        self._driver: AsyncDriver | None = None
        self._auth_tuple = auth

    async def startup(self) -> None:
        """Initialize the Neo4j async driver."""
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=self._auth_tuple,
            max_connection_pool_size=50,
            max_connection_lifetime=0,
        )
        # Verify connectivity
        try:
            await self._driver.verify_connectivity()
            log.info("neo4j_pool_started", uri=self._uri)
        except Exception as exc:
            log.warning("neo4j_connectivity_check_failed", uri=self._uri, error=str(exc))

    async def shutdown(self) -> None:
        """Close the Neo4j driver."""
        if self._driver:
            await self._driver.close()
            log.info("neo4j_pool_closed")

    def close(self) -> None:
        """Synchronously close the Neo4j driver."""
        import asyncio
        if self._driver:
            asyncio.get_event_loop().run_until_complete(self._driver.close())
            log.info("neo4j_pool_closed")

    @property
    def driver(self) -> AsyncDriver:
        """Return the Neo4j async driver.

        Raises:
            RuntimeError: If pool has not been started.
        """
        if self._driver is None:
            raise RuntimeError("Neo4jPool not started. Call startup() first.")
        return self._driver

    def session(self, database: str = "neo4j"):
        """Create a new async session.

        Args:
            database: Target database name.

        Returns:
            A new AsyncSession context manager.
        """
        if self._driver is None:
            raise RuntimeError("Neo4jPool not started. Call startup() first.")
        return self._driver.session(database=database)

    async def execute_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str = "neo4j",
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as list of dicts.

        Args:
            query: Cypher query string.
            parameters: Optional query parameters.
            database: Target database name.

        Returns:
            List of result records as dictionaries.
        """
        async with self.driver.session(database=database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records
