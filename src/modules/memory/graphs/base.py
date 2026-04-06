# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Base repository interface for graph storage."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.protocols import GraphPool


class BaseGraphRepo(ABC):
    """Abstract base class for graph repositories."""

    def __init__(self, pool: GraphPool) -> None:
        """Initialize repository with graph pool.

        Args:
            pool: Graph database connection pool.
        """
        self._pool = pool

    @abstractmethod
    async def ensure_constraints(self) -> None:
        """Create necessary constraints and indexes."""
        ...
