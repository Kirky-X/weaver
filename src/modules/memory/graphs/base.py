# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Base repository interface for graph storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol


class Neo4jPoolProtocol(Protocol):
    """Protocol for Neo4j pool interface."""

    async def execute_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str = "neo4j",
    ) -> list[dict[str, Any]]: ...


class BaseGraphRepo(ABC):
    """Abstract base class for graph repositories."""

    def __init__(self, pool: Neo4jPoolProtocol) -> None:
        """Initialize repository with Neo4j pool.

        Args:
            pool: Neo4j connection pool.
        """
        self._pool = pool

    @abstractmethod
    async def ensure_constraints(self) -> None:
        """Create necessary constraints and indexes."""
        ...
